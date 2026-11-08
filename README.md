<p align="center">
  <img src="logo.png" alt="NS Cross-check logo: two server stacks, a blue arrow between them, and a green check" width="180" height="180">
</p>

<h1 align="center">NS Cross-check</h1>

<p align="center"><strong>See whether a zone matches on the nameservers you are leaving and the ones you are moving to.</strong></p>

<p align="center">
  MIT licensed. A wrapper around dig. Python 3.10 or newer.
</p>

<p align="center">
  <a href="https://github.com/peternickol/ns-crosscheck">Repository</a>
  &nbsp;·&nbsp;
  <a href="#install">Install</a>
  &nbsp;·&nbsp;
  <a href="#check">Check</a>
  &nbsp;·&nbsp;
  <a href="#review">Review</a>
  &nbsp;·&nbsp;
  <a href="#license">License</a>
</p>

NS Cross-check runs `dig` against the old nameservers and the new nameservers,
then prints the records that differ. The terminal uses the same colors as a
diff: cyan headings, red for the old value, green for the new value, yellow
for a note.

```text
ns-crosscheck example.com --old ns1.old.net --old ns2.old.net --new ns1.new.net --new ns2.new.net
```

A matching record means those `dig` answers were the same. The delegation
section is `dig +trace`: what the registry publishes. The resolver section is
what 1.1.1.1, 8.8.8.8, and 9.9.9.9 answer. A parent or a public resolver that
still has the old names is reported. That lag leaves the exit status unchanged.

## Install

Requires **Python 3.10 or newer** and **dig** (`bind9-dnsutils` on Debian and
Ubuntu). Zone files also need `named-compilezone` from `bind9-utils`.

```bash
curl -fsSL https://raw.githubusercontent.com/peternickol/ns-crosscheck/master/install.py -o ns-crosscheck-install.py &&
python3 ns-crosscheck-install.py
```

This installs `ns-crosscheck` and `ns-crosscheck-update` into `~/.local/bin`,
without `sudo`. If that directory is missing from your `PATH`, the installer
prints the command to add it. It does not edit shell configuration. Pass
`--bin-dir` to choose another directory.

The installer downloads the current `master` branch. It refuses to replace a
source checkout or a symlink. A second run that finds the same files prints
that the program is already installed.

### Run from source

```bash
git clone https://github.com/peternickol/ns-crosscheck.git
cd ns-crosscheck
./ns-crosscheck --demo
```

### Update or uninstall

For an installer-managed copy:

```bash
ns-crosscheck --version
ns-crosscheck --update
```

`ns-crosscheck-update` runs the same updater. A source checkout is updated
with Git. To remove a default installation:

```bash
rm ~/.local/bin/ns-crosscheck ~/.local/bin/ns-crosscheck-update
```

### Platforms

Tested on Linux with Python 3.13 and BIND 9.20 `dig`. macOS is expected to
work where `dig` is installed, and has not been verified here. Native Windows
installation is not supported; use WSL.

## Check

```text
ns-crosscheck DOMAIN [--old HOST]... [--new HOST]...
                     [--old-zone FILE] [--new-zone FILE]
                     [--names FILE] [--types A,NS,...]
                     [--timeout 3] [--port 53]
                     [--no-axfr] [--no-delegation] [--no-resolvers]
                     [--strict-ttl] [--json] [--review] [--demo]
                     [--plain] [--color]
```

Each side is a list of hosts or one zone file. A host is passed to `dig` as
`@host`. The query is `+norecurse`, so the answer is the one that server
holds. The report shows the address `dig` reached and how long the SOA query
took.

Leave `--old` out and `dig +trace` supplies the current nameservers. Leave
`--new` out as well and the command checks that those servers agree with each
other.

```bash
ns-crosscheck example.com --old ns1.old.net --old ns2.old.net --new ns1.new.net --new ns2.new.net
ns-crosscheck example.com --old-zone old.zone --new ns1.new.net
ns-crosscheck example.com
ns-crosscheck --demo
```

`--demo` prints a scripted move of `example.com` and does not run `dig`.

`dig` is asked for a zone transfer. When the transfer is refused, NS
Cross-check asks `dig` for the apex, for names present on a side that did
transfer, for names in `--names`, and for in-zone names mentioned by NS, MX,
CNAME, SRV, and SOA records. It follows those names for two rounds and stops
at 2,000 names. When neither side transfers, it also asks for ordinary names:
`www`, `mail`, `ftp`, `cdn`, `cart`, `orders`, `control`, `admin`, `mailer`,
`mta-sts`, `_dmarc`, and the usual Google, Microsoft, and Mailchimp DKIM
names. When both sides are incomplete, the coverage line says that other
records may exist.

A names file is one name per line. Text after `#` is a comment. `--types`
limits the types asked when a transfer is unavailable. `--no-axfr` skips the
transfer. `--port` and `--timeout` are passed through to `dig`. The default
port is 53 and the default wait is 3 seconds. Options in `~/.digrc` are
ignored. A query that is refused or does not answer is tried again over TCP,
and then with recursion. A recursive answer is used only when the server marks
it authoritative. A non-recursive reply with the recursion-available bit set came from a
resolver on the path. The command tries IPv6, and on Linux it retries through
the route selected by a packet mark in `ip rule` when this process is allowed
to set that mark.

`--no-delegation` skips `dig +trace`. `--no-resolvers` skips the three public
resolvers. Those lookups describe the move. The exit status follows the
record comparison.

Color is on when stdout is a terminal. `NO_COLOR` and `--plain` turn it off.
`--color` turns it on anyway. `--json` prints one object.

A zone file is compiled with `named-compilezone` and then compared as text.
`$INCLUDE` and `$GENERATE` are left to that tool.

### What is a flaw

The command exits 1 when `dig` shows any of these:

- Record data differs, or a record exists on only one side.
- A server does not answer, refuses the zone, answers without the authoritative bit, or a resolver on the path answers in its place.
- Servers on the same side disagree. The copy with the highest SOA serial is the reference. Serial order follows RFC 1982.
- The new serial is behind the old serial. A new serial that is ahead is a note.
- The SOA primary name or mailbox differs. Refresh, retry, expire, and minimum differ as a note.
- The new servers publish nameserver names that still match the old hosts, or that differ from the hosts passed with `--new`.
- A nameserver inside the zone has no A or AAAA on the new side.
- The parent publishes a DS record and the new servers have no DNSKEY.

A TTL difference is a note. `--strict-ttl` makes it a flaw. Notes alone exit 0.
If one side never answers, its records stay unchecked.

### Built-in example

`ns-crosscheck --demo --plain` prints this report and exits 1. The output
below is the scripted example.

```text
example.com

Old
  ns1.old.test  192.0.2.1  SOA 2026110701  transfer of 5 names  4 ms
  ns2.old.test  192.0.2.2  SOA 2026110701  transfer of 5 names  4 ms

New
  ns1.new.test  198.51.100.1  SOA 2026110608  transfer of 5 names  4 ms
  ns2.new.test  198.51.100.2  refused the zone

Delegation
  The registry still delegates to the old servers.
  ns1.old.test
  ns2.old.test

Resolvers
  1.1.1.1 still answers with the old nameservers.
  8.8.8.8 answers with the new nameservers.
  9.9.9.9 still answers with the old nameservers.

Flaws
  ns2.new.test refused the zone at 198.51.100.2.
  example.com MX is only on the old servers.
    old  10 mail.example.com.
    new  (none)
  The new serial 2026110608 is behind the old serial 2026110701.
  example.com TXT differs.
    old  "v=spf1 include:_spf.old.test -all"
    new  "v=spf1 include:_spf.new.test -all"
  www.example.com A differs.
    old  192.0.2.10
    new  192.0.2.80
  The new servers still publish the old nameserver names (ns1.old.test, ns2.old.test).

Notes
  calendar.example.com CNAME TTL is 3600 on the old servers and 300 on the new servers.

Checked 5 names from zone transfers.
5 names. 2 match. 2 differ. 1 has a note.
```

## Review

`--review` prints the report, then walks each name that is not a clean match.
On a terminal it waits: Enter for the next name, `p` for the previous, `q` to
stop. Each name includes the `dig` command that asks that server again. A
pipe prints the same names and does not wait.

```bash
ns-crosscheck example.com --old ns1.old.net --new ns1.new.net --review
ns-crosscheck --demo --review
```

## Exit status

| Status | Meaning |
| --- | --- |
| 0 | No flaws. Notes are allowed. |
| 1 | One or more flaws. |
| 2 | Usage error, or `dig` could not be started. |
| 130 | Interrupted. |

## Develop

The command is [`ns-crosscheck`](ns-crosscheck). Tests live in [`tests/`](tests/)
and use a stand-in `dig` so they stay on this machine.

```bash
python3 -m unittest discover -s tests -t .
git diff --check
```

To install from a checkout without downloading:

```bash
python3 install.py --from-dir . --bin-dir /tmp/ns-crosscheck-check/bin
/tmp/ns-crosscheck-check/bin/ns-crosscheck --version
```

Pushing `master` makes that commit available to the installer.

## License

[MIT](LICENSE) — Copyright (c) 2026 Peter Nickol.
