# Windows manual check — no installer or remote control

This is an owner-run procedure for the existing host; the executor does not
access the PC. No admin shell, credential sharing, new installer/VPS or Algo
Trading enablement is needed. The current static DEMO UI screenshot does not
prove SDK binding or freshness. First collect file/path evidence only.

## First command: only paths and SHA256, no Python/MT5/network execution

Paste this into normal PowerShell:

```powershell
$tradingRoot = 'D:\kilas trading'
$tradingPython = 'C:\Users\ASUS ROG\Documents\Codex\2026-10-06\task\.venv\Scripts\python.exe'
$tradingNames = @(
  'demo_batch_runner.py', 'collector_diagnostic.py', 'source_batch_diagnostic.py',
  'ntp_batch_transport.py', 'clock_batch_offline.py', 'source_batch_offline.py',
  'validate_trace.py', 'read_only_mt5_measured.py', 'measured_capture_clock.py',
  'demo_risk_evidence_20261007.py'
)
$tradingPaths = @($tradingNames | ForEach-Object { Join-Path $tradingRoot $_ }) + @($tradingPython)
$tradingPaths | ForEach-Object {
  if (Test-Path -LiteralPath $_ -PathType Leaf) {
    Get-FileHash -LiteralPath $_ -Algorithm SHA256 | Select-Object Path, Hash
  } else {
    [pscustomobject]@{ Path = $_; Hash = 'MISSING' }
  }
} | Format-List
```

The output contains only paths/hash values. Parent compares all ten sources
with its already materialized ZIP. Do not replace a mismatch or change a pin.
The python.exe hash is an inventory value, not a reviewed source pin.

## Expected hashes already established

| File | Expected SHA256 |
| --- | --- |
| validate_trace.py | 6359d012d244c1098b9a58608228d1ee8c817eb49facc91b5115d8ac64992698 |
| clock_batch_offline.py | 044699f31425412b3c6ee94432d58c398fc6ec9050047178ec9ed8a31f3b049b |
| source_batch_offline.py | 68b4e85f971bb0169ad888b1058e8f1709c1ce39e3efe0e4ff80c29f542535c4 |
| read_only_mt5_measured.py | e0639f89efdb63dda82fa8dda46b80eba0a509fc4878f175a5f8c7a4a97777f4 |
| demo_risk_evidence_20261007.py | 306b8c9e0c29af906801f56176d197cce1a768d70393a4823cbb18f726002129 |

The last two are the runner's explicit reviewed source pins. The other five
source hashes must be compared to parent ZIP bytes. Do not guess them from
Library text: text access omitted one trailing byte compared to attachment
metadata in the source reads here. The request for that exact ZIP hash manifest
is with parent, not a request for owner reuploads.

## Next local-only Python presence check

Only after the path exists and source/hash comparison passes:

```powershell
& 'C:\Users\ASUS ROG\Documents\Codex\2026-10-06\task\.venv\Scripts\python.exe' -c "import sys,importlib.util; print(sys.version); print('MetaTrader5 package present:', importlib.util.find_spec('MetaTrader5') is not None)"
```

This does not import/attach to the SDK or run a broker call. Missing path/package
is a concrete setup blocker to report, not permission to install or download an
unverified replacement. Package presence alone is not producer acceptance.

## Exact one-shot runner, only after parent verifies hashes and read-only scope

Confirm the already-open terminal shows the intended DEMO server10, keep Algo
Trading off, and leave source files unchanged. The pinned ReadOnlyMT5 guards
must remain present: trade_mode0, USD, terminal connected, stable internal
identity and pre/post read verification. They check the actual SDK session
inside this invocation and stop on REAL/unknown/mismatch; the screenshot itself
cannot supply that binding. Then the existing command is:

```powershell
Set-Location -LiteralPath 'D:\kilas trading'
& 'C:\Users\ASUS ROG\Documents\Codex\2026-10-06\task\.venv\Scripts\python.exe' .\demo_batch_runner.py --read-only-demo --once
```

This is the later, explicit read-only capture step; it does perform SDK/NTP
reads, so it was not run by this executor. It requires exactly one already-open
terminal, runs once, preserves original pins, rechecks DEMO guards and shuts
down. No repeat loop or repin on failure. The current local execution helper
being unavailable does not prove a broker/network failure or justify bypass.

Return the small printed status/count result through the existing parent
workflow; the runner's short stdout does not include SDK shutdown. Keep full
report.json/private account/history local. Parent's
standalone preflight can review exact local bytes with report.sha256 and output
only its sanitized explanation, including shutdown status. No account number/password/cookies or full
diagnostic payload is needed in chat. The diagnostic remains replay only,
minimum GOLD remains governed by USD2000 cap and no AI/orders are enabled.
