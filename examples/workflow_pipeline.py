"""
Example 4: Workflow - DAG pipelines, conditional branching, and loops.

Demonstrates:
  - Workflow: DAG with parallel steps and dependencies
  - Conditional branching: skip steps based on upstream results
  - Step timeout: prevent hanging steps
  - LoopWorkflow: iterative refinement until quality threshold
"""
import asyncio
from healthy_agent.kernel.runtime import Kernel
from healthy_agent.agent.workflow import Workflow, LoopWorkflow


# -- DAG Workflow with conditions --

async def fetch_data(process, kernel):
    """Simulates fetching data. Returns None 50% of the time to demo branching."""
    await asyncio.sleep(0.05)
    return {"items": [1, 2, 3, 4, 5], "source": "api"}


async def parse_data(process, kernel):
    """Parses fetched data."""
    outputs = process.payload.get("_workflow_outputs", {})
    data = outputs.get("fetch", {})
    items = data.get("items", [])
    return {"count": len(items), "total": sum(items)}


async def validate_data(process, kernel):
    """Validates parsed data."""
    outputs = process.payload.get("_workflow_outputs", {})
    parsed = outputs.get("parse", {})
    total = parsed.get("total", 0)
    return {"valid": total > 0, "total": total}


async def generate_report(process, kernel):
    """Generates final report from validated data."""
    outputs = process.payload.get("_workflow_outputs", {})
    validation = outputs.get("validate", {})
    return f"Report: total={validation.get('total', 0)}, valid={validation.get('valid', False)}"


async def generate_error_report(process, kernel):
    """Fallback: generates error report when validation fails."""
    return "Report: ERROR - data validation failed"


async def demo_dag_workflow():
    print("=== DAG Workflow with Conditions ===\n")

    kernel = Kernel(num_cores=4)

    async def pipeline(process, kernel_ref):
        wf = Workflow(kernel_ref)
        wf.add("fetch", fetch_data)
        wf.add("parse", parse_data, depends_on=["fetch"])
        wf.add("validate", validate_data, depends_on=["parse"])
        wf.add("report", generate_report,
               depends_on=["validate"],
               condition=lambda outputs: outputs.get("validate", {}).get("valid", False))
        wf.add("error_report", generate_error_report,
               depends_on=["validate"],
               condition=lambda outputs: not outputs.get("validate", {}).get("valid", True))
        return await wf.execute(process)

    pid = kernel.spawn("pipeline", {}, handler=pipeline, preemptible=False)
    result = await kernel.exec(pid)

    print(f"  Success: {result.success}")
    print(f"  Order: {result.execution_order}")
    print(f"  Skipped: {result.skipped}")
    for name, output in result.outputs.items():
        print(f"  {name}: {output}")


# -- Loop Workflow --

async def demo_loop_workflow():
    print("\n=== Loop Workflow: Iterative Refinement ===\n")

    quality = {"score": 0.3}

    async def refine_step(process, kernel_ref):
        """Each iteration improves quality by 0.25."""
        iteration = process.payload.get("_loop_iteration", 0)
        previous = process.payload.get("_loop_previous_result")
        current_quality = quality["score"] + 0.25
        quality["score"] = current_quality
        return {
            "iteration": iteration,
            "quality": current_quality,
            "improved_from": previous,
        }

    kernel = Kernel(num_cores=2)

    async def loop_runner(process, kernel_ref):
        loop = LoopWorkflow(kernel_ref, max_iterations=10)
        return await loop.execute(
            process,
            handler=refine_step,
            stop_condition=lambda result, i: result["quality"] >= 0.9,
        )

    pid = kernel.spawn("loop_runner", {}, handler=loop_runner, preemptible=False)
    result = await kernel.exec(pid)

    print(f"  Success: {result.success}")
    print(f"  Iterations: {len(result.execution_order)}")
    for step_name, output in result.outputs.items():
        print(f"  {step_name}: quality={output['quality']:.2f}")


async def main():
    await demo_dag_workflow()
    await demo_loop_workflow()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
