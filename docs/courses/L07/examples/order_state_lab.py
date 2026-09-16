"""Check real draft-order state in a temporary database. Never calls Codex."""
from pathlib import Path
import json
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from workbench.course_experiments import ensure_product_process
ensure_product_process(__file__)
from flowerp.service import ERPService
from flowerp.store import ERPStore
from flowerp.models import OrderLine, NotFound


def run():
    with tempfile.TemporaryDirectory(prefix='l07-orders-') as temp:
        store = ERPStore(Path(temp) / 'orders.db')
        service = ERPService(store)
        service.add_product('A', '商品 A', 3000)
        service.add_product('B', '商品 B', 2000)
        stock_before = store.rows('SELECT * FROM stock ORDER BY sku')
        order = service.create_order('课堂客户', [OrderLine('A', 2, 3000),
                    OrderLine('B', 3, 2000)], 'L07-OK')
        assert order['total_cents'] == 12000
        assert order['status'] == 'draft'
        assert [x['line_total_cents'] for x in order['lines']] == [6000, 6000]
        observations = []
        for oid, lines in [('L07-INVALID', [OrderLine('A', 0, 3000)]),
                           ('L07-MISSING', [OrderLine('A', 1, 3000),
                                           OrderLine('MISSING', 1, 2000)])]:
            before = service.list_orders()
            try:
                service.create_order('课堂客户', lines, oid)
            except (ValueError, NotFound) as exc:
                kind = type(exc).__name__
            else:
                raise AssertionError('invalid order unexpectedly accepted')
            assert service.list_orders() == before
            assert not store.rows('SELECT * FROM sales_order_lines WHERE order_id=?', (oid,))
            observations.append({'order': oid, 'rejected_as': kind, 'partial_rows': 0})
        assert store.rows('SELECT * FROM stock ORDER BY sku') == stock_before
        return {'evidence_kind': 'reference_service_temp_db', 'total_cents': 12000,
                'status': order['status'], 'stock_unchanged': True,
                'failed_requests': observations, 'real_codex_event': False}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
