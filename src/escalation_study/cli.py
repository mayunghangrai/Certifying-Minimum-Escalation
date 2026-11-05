"""Commands for the escalation study: P1 and E1 passes, audit, reports, comparators and R1."""
import argparse
import csv
import json
from pathlib import Path

from .audit import audit_run
from .runner import run


def _config(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('p1', help='generate missions and certify one pass')
    p.add_argument('--config', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--phase', choices=('pass1', 'pass2'), default='pass1')
    p.add_argument('--workers', type=int, default=1)
    a = sub.add_parser('audit', help='replay every ledger and record of a P1 run')
    a.add_argument('--out', required=True)
    a.add_argument('--workers', type=int, default=1)
    r = sub.add_parser('report', help='write P1 tables and figures under analysis/')
    r.add_argument('--out', required=True)
    c = sub.add_parser('compare', help='run comparators C1-C3 on a finished P1 run')
    c.add_argument('--p1', required=True)
    c.add_argument('--config', required=True)
    c.add_argument('--out', required=True)
    c.add_argument('--workers', type=int, default=1)
    ca = sub.add_parser('compare-audit', help='re-check comparator plans and summarize them')
    ca.add_argument('--p1', required=True)
    ca.add_argument('--out', required=True)
    lg = sub.add_parser('large', help='R1 larger missions: Level 0-2 witnesses within one cap')
    lg.add_argument('--config', required=True)
    lg.add_argument('--out', required=True)
    la = sub.add_parser('large-audit', help='replay larger-mission evidence')
    la.add_argument('--out', required=True)
    e = sub.add_parser('e1', help='E1: the P1 update arriving during execution')
    e.add_argument('--config', required=True)
    e.add_argument('--out', required=True)
    e.add_argument('--phase', choices=('pass1', 'pass2'), default='pass1')
    e.add_argument('--workers', type=int, default=1)
    er = sub.add_parser('e1-report', help='level shares by update time (P1 at t=0 plus E1)')
    er.add_argument('--p1', required=True)
    er.add_argument('--e1', required=True)
    er.add_argument('--out', required=True)
    rc = sub.add_parser('runtime-compare', help='match two P1 runs by case (budget or timing reruns)')
    rc.add_argument('--reference', required=True)
    rc.add_argument('--other', required=True)
    rc.add_argument('--csv', required=True)
    args = parser.parse_args(argv)
    if args.command == 'p1':
        run(args.out, _config(args.config), phase=args.phase, workers=args.workers)
    elif args.command == 'audit':
        result = audit_run(args.out, workers=args.workers)
        print(f"audit passed: {result['missions']} missions, {result['records']} records")
    elif args.command == 'report':
        from .analysis import write_report
        print(json.dumps(write_report(args.out), indent=2))
    elif args.command == 'compare':
        from .compare import run_comparators
        run_comparators(args.out, _config(args.config), args.p1, workers=args.workers)
    elif args.command == 'compare-audit':
        from .compare import audit_comparators, summarize
        print(f'comparator plans verified: {audit_comparators(args.out, args.p1)} variants')
        print(json.dumps(summarize(args.out), indent=2))
    elif args.command == 'e1':
        from .inflight import run_e1
        run_e1(args.out, _config(args.config), phase=args.phase, workers=args.workers)
    elif args.command == 'e1-report':
        from .analysis import write_e1_report
        print(json.dumps(write_e1_report(args.p1, args.e1, args.out), indent=2))
    elif args.command == 'large':
        from .runtime import run_large
        run_large(args.out, _config(args.config))
    elif args.command == 'large-audit':
        from .runtime import audit_large
        print(json.dumps(audit_large(args.out), indent=2))
    else:
        from .runtime import compare_runs
        out = compare_runs(args.reference, args.other)
        with Path(args.csv).open('w', newline='', encoding='utf-8') as stream:
            if out:
                writer = csv.DictWriter(stream, fieldnames=list(out[0]))
                writer.writeheader()
                writer.writerows(out)
        print(f'{len(out)} matched cases written to {args.csv}')
