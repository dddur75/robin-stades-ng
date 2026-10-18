"""Sixteen processes, four collectors each, one process-shared pace."""
import os
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context

from scripts.run_mission028_details import PacedTransport as DetailTransport

PROCESSES, COLLECTORS = 16, 4


class PacedTransport(DetailTransport):
    def __init__(self, deadline, path, clock, halt):
        self.clock, self.halt = clock, halt
        super().__init__(deadline, gate_path=path)

    def check_deadline(self):
        if self.clock() >= self.deadline:
            raise RuntimeError('MISSION029_SLICE_ENDED')
        if self.halt.exists():
            raise RuntimeError('MISSION029_STOP_REQUESTED')


def process_lanes(sender, function, lanes):
    from robin.historical_deep.admission import workflow_budget
    try:
        if os.environ.get('WORKFLOW71_ADMISSION') == 'true':
            workflow_budget().cached_status()
        with ThreadPoolExecutor(max_workers=COLLECTORS) as pool:
            sender.send(list(pool.map(function, lanes)))
    finally:
        sender.close()


def parallel(function, tasks):
    width = COLLECTORS if len(tasks) < PROCESSES * COLLECTORS else PROCESSES * COLLECTORS
    lanes = [(i, tasks[i::width]) for i in range(min(len(tasks), width))]
    if width == COLLECTORS:
        with ThreadPoolExecutor(max_workers=COLLECTORS) as pool:
            return list(pool.map(function, lanes))
    context, children, results = get_context('spawn'), [], []
    try:
        for worker in range(PROCESSES):
            receiver, sender = context.Pipe(duplex=False)
            child = context.Process(target=process_lanes,
                args=(sender, function, lanes[worker::PROCESSES]))
            child.start()
            sender.close()
            children.append((child, receiver))
        failed = False
        for child, receiver in children:
            try:
                results.extend(receiver.recv())
            except EOFError:
                failed = True
        if failed:
            raise RuntimeError('MISSION029_WORKER_FAILED')
        return results
    finally:
        for child, receiver in children:
            receiver.close()
            child.join()
