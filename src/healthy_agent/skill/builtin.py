from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Tool, Skill, SkillParam, SkillResult

if TYPE_CHECKING:
    pass


# ── Tools (pure execution, no LLM) ──────────────────────────

class ReadFileTool(Tool):
    @property
    def name(self): return "read_file"
    @property
    def description(self): return "Read the content of a file at the given path."
    @property
    def parameters(self):
        return [SkillParam(name="path", type="string", description="File path to read")]

    async def execute(self, params, process=None, kernel=None):
        from pathlib import Path
        path = params.get("path", "")
        if not path:
            return SkillResult(success=False, error="Missing 'path'")
        try:
            return SkillResult(success=True, data=Path(path).read_text(encoding="utf-8", errors="replace")[:50000])
        except Exception as e:
            return SkillResult(success=False, error=str(e))


class WriteFileTool(Tool):
    @property
    def name(self): return "write_file"
    @property
    def description(self): return "Write content to a file at the given path."
    @property
    def parameters(self):
        return [
            SkillParam(name="path", type="string", description="File path to write"),
            SkillParam(name="content", type="string", description="Content to write"),
        ]

    async def execute(self, params, process=None, kernel=None):
        from pathlib import Path
        path = params.get("path", "")
        content = params.get("content", "")
        if not path:
            return SkillResult(success=False, error="Missing 'path'")
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return SkillResult(success=True, data=f"Written {len(content)} bytes to {path}")
        except Exception as e:
            return SkillResult(success=False, error=str(e))


class ShellTool(Tool):
    @property
    def name(self): return "shell"
    @property
    def description(self): return "Execute a shell command and return stdout/stderr."
    @property
    def parameters(self):
        return [SkillParam(name="command", type="string", description="Shell command")]

    async def execute(self, params, process=None, kernel=None):
        import asyncio
        command = params.get("command", "")
        if not command:
            return SkillResult(success=False, error="Missing 'command'")
        try:
            proc = await asyncio.create_subprocess_shell(
                command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            output = stdout.decode(errors="replace")[:50000]
            if proc.returncode == 0:
                return SkillResult(success=True, data=output)
            return SkillResult(success=False, data=output, error=stderr.decode(errors="replace")[:5000])
        except asyncio.TimeoutError:
            return SkillResult(success=False, error="Command timed out")


class HttpTool(Tool):
    @property
    def name(self): return "http_request"
    @property
    def description(self): return "Make an HTTP GET or POST request."
    @property
    def parameters(self):
        return [
            SkillParam(name="url", type="string", description="URL to request"),
            SkillParam(name="method", type="string", description="GET or POST", required=False),
        ]

    async def execute(self, params, process=None, kernel=None):
        import httpx
        url = params.get("url", "")
        method = params.get("method", "GET").upper()
        if not url:
            return SkillResult(success=False, error="Missing 'url'")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(method, url)
                return SkillResult(success=resp.is_success, data=resp.text[:50000])
        except Exception as e:
            return SkillResult(success=False, error=str(e))


# ── Skills (use LLM) ────────────────────────────────────────

class SummarizeSkill(Skill):
    @property
    def name(self): return "summarize"
    @property
    def description(self): return "Summarize text using LLM."
    @property
    def parameters(self):
        return [
            SkillParam(name="text", type="string", description="Text to summarize"),
            SkillParam(name="max_sentences", type="integer", description="Max sentences", required=False),
        ]

    async def execute(self, params, process=None, kernel=None):
        text = params.get("text", "")
        max_s = params.get("max_sentences", 3)
        if not text:
            return SkillResult(success=False, error="Missing 'text'")
        driver = params.get("_driver")
        if not driver:
            return SkillResult(success=True, data=f"[mock] Would summarize {len(text)} chars")
        result = await driver.generate(
            [{"role": "user", "content": f"Summarize in {max_s} sentences:\n\n{text}"}],
            system=f"Write exactly {max_s} sentences.",
        )
        return SkillResult(success=result.success, data=result.data["text"].strip() if result.success else "", error=result.error)


class CodeGenSkill(Skill):
    @property
    def name(self): return "code_gen"
    @property
    def description(self): return "Generate code using LLM."
    @property
    def parameters(self):
        return [
            SkillParam(name="task", type="string", description="What code to write"),
            SkillParam(name="language", type="string", description="Programming language", required=False),
        ]

    async def execute(self, params, process=None, kernel=None):
        task = params.get("task", "")
        lang = params.get("language", "Python")
        if not task:
            return SkillResult(success=False, error="Missing 'task'")
        driver = params.get("_driver")
        if not driver:
            return SkillResult(success=True, data=f"[mock] Would generate {lang} code for: {task}")
        result = await driver.generate(
            [{"role": "user", "content": f"Write {lang} code: {task}. Output only code."}],
            system="Output only raw code, no markdown.",
        )
        return SkillResult(success=result.success, data=result.data["text"].strip() if result.success else "", error=result.error)


class WebSearchSkill(Skill):
    @property
    def name(self): return "web_search"
    @property
    def description(self): return "Search the web for information."
    @property
    def parameters(self):
        return [SkillParam(name="query", type="string", description="Search query")]

    async def execute(self, params, process=None, kernel=None):
        query = params.get("query", "")
        if not query:
            return SkillResult(success=False, error="Missing 'query'")
        return SkillResult(success=True, data=f"[mock] Would search: {query}")


# ── Sorting Tool ─────────────────────────────────────────────

class SortTool(Tool):
    """Sort a list of items using various algorithms.

    Supports: quicksort, mergesort, bubblesort, insertionsort, heapsort,
              selectionsort, python (built-in Timsort).
    Items can be numbers or strings. Supports ascending/descending order.
    Returns the sorted list and a step-by-step trace when requested.
    """

    @property
    def name(self): return "sort"

    @property
    def description(self):
        return (
            "Sort a list of items. Supports multiple algorithms "
            "(quicksort, mergesort, bubblesort, insertionsort, heapsort, "
            "selectionsort, python), ascending/descending order, and "
            "optional step-by-step trace."
        )

    @property
    def parameters(self):
        return [
            SkillParam(name="items", type="array",
                       description="List of items to sort (numbers or strings). "
                                   "Can also be a comma-separated string, e.g. '3,1,2'."),
            SkillParam(name="algorithm", type="string",
                       description="Sorting algorithm: quicksort | mergesort | bubblesort | "
                                   "insertionsort | heapsort | selectionsort | python (default: python)",
                       required=False),
            SkillParam(name="order", type="string",
                       description="Sort order: asc (default) | desc",
                       required=False),
            SkillParam(name="key", type="string",
                       description="Sort type: auto (default) | numeric | string",
                       required=False),
            SkillParam(name="trace", type="boolean",
                       description="If true, include a step-by-step trace of the algorithm (default: false)",
                       required=False),
        ]

    # ── public entry ──

    async def execute(self, params, process=None, kernel=None):
        # --- parse items ---
        raw = params.get("items", [])
        if isinstance(raw, str):
            raw = [x.strip() for x in raw.split(",") if x.strip()]
        if not isinstance(raw, list) or len(raw) == 0:
            return SkillResult(success=False, error="Missing or empty 'items'")

        # --- decide numeric vs string ---
        key_mode = params.get("key", "auto")
        items = self._coerce(raw, key_mode)

        algorithm = params.get("algorithm", "python").lower().replace("_", "").replace("-", "")
        reverse = params.get("order", "asc").lower().startswith("desc")
        want_trace = bool(params.get("trace", False))

        algo_map = {
            "python":        self._sort_python,
            "quicksort":     self._sort_quick,
            "mergesort":     self._sort_merge,
            "bubblesort":    self._sort_bubble,
            "insertionsort": self._sort_insertion,
            "heapsort":      self._sort_heap,
            "selectionsort": self._sort_selection,
        }

        fn = algo_map.get(algorithm)
        if fn is None:
            return SkillResult(
                success=False,
                error=f"Unknown algorithm '{algorithm}'. "
                      f"Choose from: {', '.join(algo_map)}",
            )

        try:
            trace: list[str] = []
            sorted_items = fn(list(items), trace if want_trace else None)
            if reverse:
                sorted_items = list(reversed(sorted_items))
            result = {
                "sorted": sorted_items,
                "algorithm": algorithm,
                "order": "desc" if reverse else "asc",
                "length": len(sorted_items),
            }
            if want_trace:
                result["trace"] = trace
            return SkillResult(success=True, data=result)
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    # ── coercion helper ──

    @staticmethod
    def _coerce(raw: list, mode: str) -> list:
        if mode == "string":
            return [str(x) for x in raw]
        if mode == "numeric":
            return [float(x) if "." in str(x) else int(x) for x in raw]
        # auto: try numeric first
        try:
            return [float(x) if "." in str(x) else int(x) for x in raw]
        except (ValueError, TypeError):
            return [str(x) for x in raw]

    # ── algorithm implementations ──

    @staticmethod
    def _sort_python(arr: list, trace: list[str] | None) -> list:
        if trace is not None:
            trace.append(f"Input:  {arr}")
        result = sorted(arr)
        if trace is not None:
            trace.append(f"Output: {result}  (Python Timsort)")
        return result

    # -- quicksort --

    @staticmethod
    def _sort_quick(arr: list, trace: list[str] | None) -> list:
        if trace is not None:
            trace.append(f"quicksort({arr})")
        if len(arr) <= 1:
            return arr
        pivot = arr[len(arr) // 2]
        left  = [x for x in arr if x < pivot]
        mid   = [x for x in arr if x == pivot]
        right = [x for x in arr if x > pivot]
        if trace is not None:
            trace.append(f"  pivot={pivot}  left={left}  mid={mid}  right={right}")
        return SortTool._sort_quick(left, trace) + mid + SortTool._sort_quick(right, trace)

    # -- mergesort --

    @staticmethod
    def _sort_merge(arr: list, trace: list[str] | None) -> list:
        if len(arr) <= 1:
            return arr
        mid_idx = len(arr) // 2
        left  = SortTool._sort_merge(arr[:mid_idx], trace)
        right = SortTool._sort_merge(arr[mid_idx:], trace)
        merged = SortTool._merge(left, right)
        if trace is not None:
            trace.append(f"merge({left}, {right}) -> {merged}")
        return merged

    @staticmethod
    def _merge(a: list, b: list) -> list:
        result, i, j = [], 0, 0
        while i < len(a) and j < len(b):
            if a[i] <= b[j]:
                result.append(a[i])
                i += 1
            else:
                result.append(b[j])
                j += 1
        result.extend(a[i:])
        result.extend(b[j:])
        return result

    # -- bubblesort --

    @staticmethod
    def _sort_bubble(arr: list, trace: list[str] | None) -> list:
        n = len(arr)
        for i in range(n):
            swapped = False
            for j in range(n - 1 - i):
                if arr[j] > arr[j + 1]:
                    arr[j], arr[j + 1] = arr[j + 1], arr[j]
                    swapped = True
            if trace is not None:
                trace.append(f"Pass {i + 1}: {arr}")
            if not swapped:
                break
        return arr

    # -- insertionsort --

    @staticmethod
    def _sort_insertion(arr: list, trace: list[str] | None) -> list:
        for i in range(1, len(arr)):
            key = arr[i]
            j = i - 1
            while j >= 0 and arr[j] > key:
                arr[j + 1] = arr[j]
                j -= 1
            arr[j + 1] = key
            if trace is not None:
                trace.append(f"Insert {key} -> {arr}")
        return arr

    # -- heapsort --

    @staticmethod
    def _sort_heap(arr: list, trace: list[str] | None) -> list:
        import heapq
        heapq.heapify(arr)
        result = []
        while arr:
            result.append(heapq.heappop(arr))
        if trace is not None:
            trace.append(f"Heapsort result: {result}")
        return result

    # -- selectionsort --

    @staticmethod
    def _sort_selection(arr: list, trace: list[str] | None) -> list:
        n = len(arr)
        for i in range(n):
            min_idx = i
            for j in range(i + 1, n):
                if arr[j] < arr[min_idx]:
                    min_idx = j
            arr[i], arr[min_idx] = arr[min_idx], arr[i]
            if trace is not None:
                trace.append(f"Step {i + 1}: select {arr[i]}, arr={arr}")
        return arr
