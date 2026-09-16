"""Teaching experiment: observe real temporary ERP state with an optional bad caller.

--defect deliberately assigns a new identity to a retry. It demonstrates an
integration defect, not a claim that the repository's service lacks idempotency.
Never opens the learner's runtime database or invokes Codex.
"""
from pathlib import Path
import argparse
import json
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from workbench.course_experiments import ensure_product_process
ensure_product_process(__file__)
from flowerp.service import ERPService
from flowerp.store import ERPStore


def run_case(defect: bool = False, opening: int = 20, quantity: int = 8) -> dict:
    if opening <= 0 or quantity <= 0:
        raise ValueError('教学起点与本次收货数量必须大于0')
    with tempfile.TemporaryDirectory(prefix='l05-receiving-') as temporary:
        store = ERPStore(Path(temporary) / 'case.db')
        service = ERPService(store)
        sku = 'L05-EXAMPLE'
        service.add_product(sku, '课堂商品', 1000)
        service.receive_stock(sku, opening, 'opening')
        calls = 0

        def receive(quantity: int, key: str):
            nonlocal calls
            calls += 1
            # This explicit teaching switch models a caller losing retry identity.
            effective_key = f'{key}-attempt-{calls}' if defect else key
            return service.receive_stock(sku, quantity, effective_key)

        def state():
            return {
                'on_hand': service.product(sku)['on_hand'],
                'events': store.rows(
                    'SELECT event_key,sku,quantity,reserved_delta,event_type,reference '
                    'FROM inventory_events WHERE sku=? ORDER BY event_key', (sku,)),
            }

        expected_first = opening + quantity
        expected_new = opening + quantity * 2
        receive(quantity, 'receipt-A')
        first = state()
        receive(quantity, 'receipt-A')
        replay = state()
        if first['on_hand'] != expected_first or len(first['events']) != 2:
            raise AssertionError(f'AC-FIRST 期望库存={expected_first}且共2条流水，实际={first}')
        if replay != first:
            raise AssertionError(
                f'AC-REPLAY 同一请求重试必须保持库存和流水；'
                f'期望库存={expected_first}，实际={replay["on_hand"]}；'
                f'期望流水数=2，实际={len(replay["events"])}')
        receive(quantity, 'receipt-B')
        independent = state()
        if independent['on_hand'] != expected_new or len(independent['events']) != 3:
            raise AssertionError(f'AC-NEW 期望库存={expected_new}且共3条流水，实际={independent}')
        for invalid in (0, -1):
            before = state()
            try:
                receive(invalid, f'invalid-{invalid}')
            except ValueError:
                pass
            else:
                raise AssertionError(f'AC-INVALID 数量={invalid}应拒绝，实际被接受')
            if state() != before:
                raise AssertionError(f'AC-UNCHANGED 数量={invalid}被拒绝后改变了库存或流水')
        return {'case': 'receiving_identity_and_ledger', 'status': 'pass',
                'first_on_hand': first['on_hand'], 'replay_on_hand': replay['on_hand'],
                'new_on_hand': independent['on_hand'], 'replay_events': len(replay['events']),
                'invalid_quantities_rejected': [0, -1], 'failure_state_unchanged': True,
                'mode': 'teaching_defect' if defect else 'reference_service'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--defect', action='store_true')
    parser.add_argument('--opening', type=int, default=20)
    parser.add_argument('--quantity', type=int, default=8)
    args = parser.parse_args()
    try:
        result = run_case(args.defect, args.opening, args.quantity)
    except AssertionError as error:
        print(json.dumps({'case': 'receiving_identity_and_ledger', 'status': 'fail',
                          'reason': str(error), 'teaching_defect': args.defect}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
