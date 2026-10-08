"""在全新教学目录验证恢复点和拒绝后的状态；不操作已有运行库。"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from workbench.course_experiments import ensure_product_process
ensure_product_process(__file__)

from flowerp import ERPStore, ERPService
from flowerp.operations import BackupService


def run(destination: Path) -> dict:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    store = ERPStore(destination / 'source' / 'flowerp.db')
    erp = ERPService(store)
    erp.add_product('RESTORE-16', '恢复实验商品', 100, 1)
    erp.receive_stock('RESTORE-16', 8, 'receipt-before-backup')
    at_backup = erp.product('RESTORE-16')['on_hand']
    backup = BackupService(store, destination / 'backups')
    created = backup.create('lesson16')
    erp.receive_stock('RESTORE-16', 2, 'receipt-after-backup')
    current = erp.product('RESTORE-16')['on_hand']
    target = destination / 'restored' / 'flowerp.db'
    started = time.perf_counter()
    restored = backup.restore(created['backup'], target)
    elapsed = time.perf_counter() - started
    recovered_erp = ERPService(ERPStore(target))
    recovered = recovered_erp.product('RESTORE-16')['on_hand']
    recovered_events = recovered_erp.inventory_events()
    source_events = erp.inventory_events()
    assert (at_backup, current, recovered) == (8, 10, 8)
    assert len(source_events) == 2 and len(recovered_events) == 1
    before_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    try:
        backup.restore(created['backup'], target)
    except FileExistsError:
        duplicate = 'FileExistsError'
    else:
        raise AssertionError('应拒绝覆盖已存在的恢复库')
    after_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    assert before_hash == after_hash
    damaged_dir = destination / 'damaged-copy'
    damaged_dir.mkdir()
    damaged = damaged_dir / Path(created['backup']).name
    shutil.copyfile(created['backup'], damaged)
    shutil.copyfile(created['manifest'], damaged_dir / Path(created['manifest']).name)
    with damaged.open('ab') as stream:
        stream.write(b'lesson16-controlled-corruption')
    rejected_target = destination / 'rejected' / 'flowerp.db'
    try:
        backup.restore(damaged, rejected_target)
    except RuntimeError:
        damaged_result = 'RuntimeError'
    else:
        raise AssertionError('应拒绝指纹不符的备份副本')
    assert not rejected_target.exists()
    assert backup.verify(created['backup'])['ok']
    assert erp.product('RESTORE-16')['on_hand'] == 10
    report = {
        'kind': 'controlled-reference-experiment',
        'is_cold_start': False, 'is_production_rollback': False,
        'at_backup': at_backup, 'source_after_new_receipt': current,
        'restored_quantity': recovered,
        'source_event_keys': [x['event_key'] for x in source_events],
        'restored_event_keys': [x['event_key'] for x in recovered_events],
        'restore_seconds': round(elapsed, 4),
        'restore_integrity': restored['integrity'],
        'duplicate_restore': {'error': duplicate, 'target_hash_unchanged': before_hash == after_hash},
        'damaged_copy_restore': {'error': damaged_result, 'target_exists': rejected_target.exists()},
        'original_backup_valid': True, 'source_final_quantity': 10,
        'lesson': '恢复正确地回到8件；备份后新增2件不在恢复副本中，不能直接覆盖当前业务库。',
    }
    (destination / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path, help='必须是尚不存在的新目录')
    print(json.dumps(run(parser.parse_args().output_dir), ensure_ascii=False, indent=2))
