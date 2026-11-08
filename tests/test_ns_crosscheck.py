import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / 'ns-crosscheck'

DIG = textwrap.dedent("""\
    #!/usr/bin/env python3
    import os
    import sys
    from pathlib import Path
    args = sys.argv[1:]
    root = Path(os.environ['NSC_FIXTURE'])
    with (root / 'calls').open('a', encoding='utf-8') as stream:
        stream.write(' '.join(args) + '\\n')
    if '+trace' in args:
        path = root / (('trace_tcp_' if '+tcp' in args else 'trace_') + args[0])
    else:
        path = root / f'{args[0][1:]}__{args[3]}__{args[4]}{"__tcp" if "+tcp" in args else ""}'
    if not path.is_file():
        host = args[0][1:] if args and args[0].startswith('@') else ''
        if host and any(item.name.startswith(host + '__') for item in root.iterdir()):
            sys.stdout.write(
                '- type: MESSAGE\\n'
                '  message:\\n'
                '    response_address: "192.0.2.1"\\n'
                '    query_time: !!timestamp 2026-11-07T00:00:00.000Z\\n'
                '    response_time: !!timestamp 2026-11-07T00:00:00.004Z\\n'
                '    response_message_data:\\n'
                '      status: NOERROR\\n'
                '      flags: qr aa\\n'
                '      OPT_PSEUDOSECTION:\\n'
                '        EDNS:\\n'
                '          flags:\\n'
                '      ANSWER_SECTION:\\n'
                '        []\\n'
            )
            raise SystemExit(0)
        print(';; connection timed out; no servers could be reached')
        raise SystemExit(9)
    sys.stdout.write(path.read_text(encoding='utf-8'))
""")

COMPILE = textwrap.dedent("""\
    #!/usr/bin/env python3
    import sys
    from pathlib import Path
    sys.stdout.write(Path(sys.argv[-1]).read_text(encoding='utf-8'))
""")


def message(address, status, flags, answers):
    lines = [
        '- type: MESSAGE',
        '  message:',
        f'    response_address: "{address}"',
        '    query_time: !!timestamp 2026-11-07T00:00:00.000Z',
        '    response_time: !!timestamp 2026-11-07T00:00:00.004Z',
        '    response_message_data:',
        f'      status: {status}',
        f'      flags: {flags}',
        '      OPT_PSEUDOSECTION:',
        '        EDNS:',
        '          flags:',
        '      ANSWER_SECTION:',
    ]
    if answers:
        lines.extend(f"        - '{item}'" for item in answers)
    else:
        lines.append('        []')
    return '\n'.join(lines) + '\n'


def zone(*records):
    closing = records[0]
    return '\n'.join((*records, closing)) + '\n'


OLD = zone(
    'example.com. 3600 IN SOA ns1.old.test. host.example.com. 10 1 1 1 1',
    'example.com. 3600 IN NS ns1.old.test.',
    'example.com. 3600 IN A 192.0.2.10',
    'www.example.com. 3600 IN A 192.0.2.20',
)
CHANGED = zone(
    'example.com. 3600 IN SOA ns1.old.test. host.example.com. 9 1 1 1 1',
    'example.com. 3600 IN NS ns1.old.test.',
    'example.com. 3600 IN A 192.0.2.10',
    'www.example.com. 3600 IN A 192.0.2.80',
)


class ToolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        dig = self.bin / 'dig'
        dig.write_text(DIG)
        dig.chmod(dig.stat().st_mode | stat.S_IEXEC)
        compilezone = self.bin / 'named-compilezone'
        compilezone.write_text(COMPILE)
        compilezone.chmod(compilezone.stat().st_mode | stat.S_IEXEC)
        self.fixture = self.root / 'fixture'
        self.fixture.mkdir()
        (self.fixture / 'calls').write_text('')

    def place(self, host, name, rtype, body):
        (self.fixture / f'{host}__{name}__{rtype}').write_text(body)

    def command(self, *args, path=None):
        env = os.environ.copy()
        if path is None:
            env['PATH'] = str(self.bin) + os.pathsep + env.get('PATH', '')
        else:
            env['PATH'] = path
        env['NSC_FIXTURE'] = str(self.fixture)
        env.pop('NO_COLOR', None)
        return subprocess.run(
            [sys.executable, str(PROGRAM), *args],
            cwd=ROOT, capture_output=True, text=True, check=False, env=env,
        )

    def test_demo_matches_the_sample_move(self):
        demo = self.command('--demo', '--plain', path='/usr/bin')
        self.assertEqual(demo.returncode, 1, demo.stderr)
        self.assertIn('www.example.com A differs.', demo.stdout)
        self.assertIn('The new serial 2026110608 is behind the old serial 2026110701.', demo.stdout)
        self.assertIn('The new servers still publish the old nameserver names (ns1.old.test, ns2.old.test).', demo.stdout)
        self.assertIn('calendar.example.com CNAME TTL is 3600 on the old servers and 300 on the new servers.', demo.stdout)
        self.assertIn('5 names. 2 match. 2 differ. 1 has a note.', demo.stdout)
        self.assertNotIn('\033', demo.stdout)
        colored = self.command('--demo', '--color', path='/usr/bin')
        self.assertIn('\033[1;36m', colored.stdout)
        self.assertIn('\033[31m', colored.stdout)
        self.assertIn('\033[32m', colored.stdout)
        version = self.command('--version', path='/usr/bin')
        self.assertEqual(version.stdout.strip(), 'ns-crosscheck 0.1.1')

    def test_dig_transfer_reports_the_move(self):
        self.place('ns1.old.test', 'example.com', 'SOA', message(
            '192.0.2.1', 'NOERROR', 'qr aa',
            ['example.com. 3600 IN SOA ns1.old.test. host.example.com. 10 1 1 1 1'],
        ))
        self.place('ns1.old.test', 'example.com', 'AXFR', message('192.0.2.1', 'NOERROR', 'qr aa', OLD.splitlines()))
        self.place('ns1.new.test', 'example.com', 'SOA', message(
            '198.51.100.1', 'NOERROR', 'qr aa',
            ['example.com. 3600 IN SOA ns1.old.test. host.example.com. 9 1 1 1 1'],
        ))
        self.place('ns1.new.test', 'example.com', 'AXFR', message('198.51.100.1', 'NOERROR', 'qr aa', CHANGED.splitlines()))
        result = self.command(
            'example.com', '--old', 'ns1.old.test', '--new', 'ns1.new.test',
            '--no-delegation', '--no-resolvers', '--plain',
        )
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn('www.example.com A differs.', result.stdout)
        self.assertIn('The new serial 9 is behind the old serial 10.', result.stdout)
        self.assertIn('The new servers still publish the old nameserver names (ns1.old.test).', result.stdout)
        calls = (self.fixture / 'calls').read_text()
        self.assertIn('@ns1.old.test -p 53 example.com AXFR', calls)
        self.assertIn('+norecurse', calls)
        self.assertIn('+yaml', calls)
        review = self.command(
            'example.com', '--old', 'ns1.old.test', '--new', 'ns1.new.test',
            '--no-delegation', '--no-resolvers', '--review', '--plain',
        )
        self.assertEqual(review.returncode, 1, review.stderr)
        self.assertIn('dig @198.51.100.1 www.example.com A +norecurse', review.stdout)
        self.assertNotIn('\n> ', '\n' + review.stdout)

    def test_a_silent_server_is_not_a_missing_record(self):
        self.place('ns1.old.test', 'example.com', 'SOA', message(
            '192.0.2.1', 'NOERROR', 'qr aa',
            ['example.com. 3600 IN SOA ns1.old.test. host.example.com. 10 1 1 1 1'],
        ))
        self.place('ns1.old.test', 'example.com', 'AXFR', message('192.0.2.1', 'NOERROR', 'qr aa', OLD.splitlines()))
        result = self.command(
            'example.com', '--old', 'ns1.old.test', '--new', 'ns1.new.test',
            '--no-delegation', '--no-resolvers', '--plain',
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('ns1.new.test did not answer', result.stdout)
        self.assertNotIn('only on the old servers', result.stdout)

    def test_refused_transfer_queries_the_names_dig_already_has(self):
        zone_file = self.root / 'old.zone'
        zone_file.write_text(
            'example.com. 3600 IN SOA ns1.old.test. host.example.com. 1 1 1 1 1\n'
            'example.com. 3600 IN NS ns1.old.test.\n'
            'www.example.com. 3600 IN A 192.0.2.10\n'
        )
        self.place('ns1.new.test', 'example.com', 'SOA', message(
            '198.51.100.1', 'NOERROR', 'qr aa',
            ['example.com. 3600 IN SOA ns1.old.test. host.example.com. 1 1 1 1 1'],
        ))
        self.place('ns1.new.test', 'example.com', 'AXFR', message('198.51.100.1', 'REFUSED', 'qr', []))
        self.place('ns1.new.test', 'example.com', 'NS', message(
            '198.51.100.1', 'NOERROR', 'qr aa', ['example.com. 3600 IN NS ns1.old.test.'],
        ))
        self.place('ns1.new.test', 'www.example.com', 'A', message(
            '198.51.100.1', 'NOERROR', 'qr aa', ['www.example.com. 3600 IN A 192.0.2.80'],
        ))
        result = self.command(
            'example.com', '--old-zone', str(zone_file), '--new', 'ns1.new.test',
            '--no-delegation', '--no-resolvers', '--plain',
        )
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn('www.example.com A differs.', result.stdout)
        self.assertIn('one name at a time', result.stdout)
        self.assertNotIn('secret.example.com', result.stdout)

    def test_refused_transfers_still_compare_the_apex_and_ordinary_names(self):
        soa = 'example.com. 3600 IN SOA ns1.old.test. host.example.com. 1 1 1 1 1'
        for host, address, address_a in (
            ('ns1.old.test', '192.0.2.1', '192.0.2.10'),
            ('ns1.new.test', '198.51.100.1', '192.0.2.80'),
        ):
            self.place(host, 'example.com', 'SOA', message(address, 'NOERROR', 'qr aa', [soa]))
            self.place(host, 'example.com', 'AXFR', message(address, 'FORMERR', 'qr', []))
            self.place(host, 'example.com', 'A', message(
                address, 'NOERROR', 'qr aa', [f'example.com. 300 IN A {address_a}'],
            ))
            self.place(host, 'www.example.com', 'A', message(
                address, 'NOERROR', 'qr aa', [f'www.example.com. 300 IN A {address_a}'],
            ))
        result = self.command(
            'example.com', '--old', 'ns1.old.test', '--new', 'ns1.new.test',
            '--no-delegation', '--no-resolvers', '--plain',
        )
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn('example.com A differs.', result.stdout)
        self.assertIn('www.example.com A differs.', result.stdout)
        self.assertIn('transfer refused', result.stdout)
        self.assertNotIn('authoritative bit', result.stdout)
        calls = (self.fixture / 'calls').read_text()
        self.assertIn('@ns1.old.test -p 53 _dmarc.example.com TXT', calls)
        self.assertNotIn('secret.example.com', calls)

    def test_udp_refusal_is_tried_over_tcp(self):
        soa = 'example.com. 3600 IN SOA ns1.old.test. host.example.com. 1 1 1 1 1'
        for host, address, address_a in (
            ('ns1.old.test', '192.0.2.1', '192.0.2.10'),
            ('ns1.new.test', '198.51.100.1', '192.0.2.80'),
        ):
            self.place(host, 'example.com', 'SOA', message(address, 'REFUSED', 'qr', []))
            self.place(host, 'example.com', 'SOA__tcp', message(address, 'NOERROR', 'qr aa', [soa]))
            self.place(host, 'example.com', 'AXFR__tcp', message(address, 'NOTIMP', 'qr', []))
            self.place(host, 'example.com', 'A__tcp', message(
                address, 'NOERROR', 'qr aa', [f'example.com. 300 IN A {address_a}'],
            ))
        result = self.command(
            'example.com', '--old', 'ns1.old.test', '--new', 'ns1.new.test',
            '--no-delegation', '--no-resolvers', '--plain',
        )
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn('example.com A differs.', result.stdout)
        self.assertNotIn('refused the zone', result.stdout)
        calls = (self.fixture / 'calls').read_text()
        self.assertIn('@ns1.old.test -p 53 example.com SOA', calls)
        self.assertIn('+tcp', calls)

    def test_trace_and_review_stay_with_dig(self):
        (self.fixture / 'trace_example.com').write_text(
            '. 100 IN NS a.root-servers.net.\n'
            ';; Received 20 bytes from 1.1.1.1#53(1.1.1.1) in 1 ms\n'
            'example.com. 100 IN NS ns1.old.test.\n'
            'example.com. 100 IN DS 12345 8 2 abcd\n'
            ';; Received 40 bytes from 192.5.6.30#53(a.gtld-servers.net) in 2 ms\n'
        )
        self.place('ns1.old.test', 'example.com', 'SOA', message(
            '192.0.2.1', 'NOERROR', 'qr aa',
            ['example.com. 3600 IN SOA ns1.old.test. host.example.com. 10 1 1 1 1'],
        ))
        self.place('ns1.old.test', 'example.com', 'AXFR', message('192.0.2.1', 'NOERROR', 'qr aa', OLD.splitlines()))
        self.place('1.1.1.1', 'example.com', 'NS', message('1.1.1.1', 'NOERROR', 'qr rd ra', ['example.com. 30 IN NS ns1.old.test.']))
        self.place('8.8.8.8', 'example.com', 'NS', message('8.8.8.8', 'NOERROR', 'qr rd ra', ['example.com. 30 IN NS ns1.old.test.']))
        self.place('9.9.9.9', 'example.com', 'NS', message('9.9.9.9', 'NOERROR', 'qr rd ra', ['example.com. 30 IN NS ns1.old.test.']))
        result = self.command('example.com', '--old', 'ns1.old.test', '--plain')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('The registry delegates to these servers.', result.stdout)
        self.assertIn('1.1.1.1 answers with these servers.', result.stdout)
        review = self.command('example.com', '--old', 'ns1.old.test', '--no-delegation', '--no-resolvers', '--review', '--plain')
        self.assertEqual(review.returncode, 0, review.stderr)
        self.assertIn('Every compared name matches.', review.stdout)
        self.assertNotIn('>', review.stdout)

    def test_missing_dig_is_an_error_and_the_demo_is_not(self):
        empty = self.root / 'empty'
        empty.mkdir()
        missing = self.command('example.com', '--old', 'ns1.old.test', '--no-delegation', '--no-resolvers', path=str(empty))
        self.assertEqual(missing.returncode, 2)
        self.assertIn('dig is not installed', missing.stderr)
        demo = self.command('--demo', '--plain', path=str(empty))
        self.assertEqual(demo.returncode, 1)


class InstallTest(unittest.TestCase):
    def test_local_install_runs_the_demo(self):
        with tempfile.TemporaryDirectory() as directory:
            bindir = Path(directory) / 'bin'
            result = subprocess.run(
                [sys.executable, str(ROOT / 'install.py'), '--from-dir', str(ROOT), '--bin-dir', str(bindir)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Installed NS Cross-check', result.stdout)
            version = subprocess.run([str(bindir / 'ns-crosscheck'), '--version'], check=False, capture_output=True, text=True)
            self.assertEqual(version.stdout.strip(), 'ns-crosscheck 0.1.1')
            again = subprocess.run(
                [sys.executable, str(ROOT / 'install.py'), '--from-dir', str(ROOT), '--bin-dir', str(bindir)],
                check=False, capture_output=True, text=True,
            )
            self.assertIn('already installed', again.stdout)


if __name__ == '__main__':
    unittest.main()
