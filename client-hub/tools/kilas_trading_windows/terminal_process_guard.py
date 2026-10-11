"""Read-only existing-terminal detection; never launches or attaches MT5."""
import csv
import io
import json
import ntpath
import subprocess

SCRIPT=("$p=@(Get-Process -Name terminal64 -ErrorAction SilentlyContinue); "
        "$r=@($p | ForEach-Object { [pscustomobject]@{pid=$_.Id;session=$_.SessionId;executable=$_.Path} }); "
        "ConvertTo-Json -InputObject $r -Compress")

def inspect_terminal(expected_exe,*,runner=subprocess.run):
    report={'verified':False,'method':'NONE','process_count':None,
            'executable_verified':False,'settings_changed':False}
    count=None
    try:
        r=runner(['tasklist.exe','/FI','IMAGENAME eq terminal64.exe','/FO','CSV','/NH'],
            capture_output=True,text=True,timeout=2,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if r.returncode==0:
            rows=list(csv.reader(io.StringIO(r.stdout)))
            count=sum(bool(row) and row[0].lower()=='terminal64.exe' for row in rows)
            if count!=1: return dict(report,method='TASKLIST',process_count=count)
    except Exception: pass
    try:
        # Use native process metadata if tasklist fails, and also verify the
        # executable behind a successful name count. No CIM/auth bypass/UI use.
        r=runner(['powershell.exe','-NoProfile','-NonInteractive','-Command',SCRIPT],
            capture_output=True,text=True,timeout=2,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if r.returncode!=0 or len(r.stdout.encode('utf8'))>4096: return report
        records=json.loads(r.stdout)
        if type(records) is not list: return report
        report.update(method='NATIVE_FALLBACK' if count is None else 'TASKLIST_AND_NATIVE',process_count=len(records))
        if len(records)!=1: return report
        p=records[0]
        if (type(p) is not dict or set(p)!={'pid','session','executable'}
            or type(p['pid']) is not int or p['pid']<=0
            or type(p['session']) is not int or p['session']<=0
            or type(p['executable']) is not str): return report
        matched=ntpath.normcase(ntpath.normpath(p['executable']))==ntpath.normcase(ntpath.normpath(expected_exe))
        report.update(verified=matched,executable_verified=matched,pid=p['pid'],session=p['session'])
        return report
    except Exception: return report
