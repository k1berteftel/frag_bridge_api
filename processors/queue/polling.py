from processors.queue.aggregator import QueueManager
from models import AggregatorStatus


async def polling_task(task_id, queues: QueueManager) -> dict | None:
    tasks = await queues.get_tasks()
    for task in tasks:
        if task.get('id') == task_id:
            if task.get('status') == AggregatorStatus.COMPLETED.value:
                await queues.del_task(task_id)
                return {
                    'status': True,
                    'tx_hash': task['result'].get('tx_hash'),
                    'sum': task['result'].get('sum'),
                    'cost': task['result'].get('cost'),
                    'fee': task['result'].get('fee')
                }
            if task.get('status') == AggregatorStatus.FAILED.value:
                return {
                    'status': False,
                    'code': task['result'].get('code'),
                    'message': task['result'].get('error')
                }
    return None