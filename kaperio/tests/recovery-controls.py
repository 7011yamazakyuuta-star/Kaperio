"""Exercise actual Hashcat pause/restore and fixed-prefix masks."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Library
from recovery import has_checkpoint
from test_core import make_pdf

root=Path(__file__).resolve().parents[1]/'.test-data'/'controls'
root.mkdir(parents=True,exist_ok=True)
lib=Library(root/('library-' + str(time.time_ns())))


def until(predicate,seconds=50):
    limit=time.monotonic()+seconds
    while not predicate():
        if time.monotonic()>limit:raise TimeoutError('Recovery control test timed out')
        time.sleep(.2)


try:
    source=root/'mask.pdf';make_pdf(source,'Aab9')
    jid=lib.import_pdf(source.name,source.read_bytes())
    if not lib.jobs[jid].get('unlocked'):
        lib.start_recovery(jid,{'strategy':'mask','prefix':'A','suffix':'9','min':4,'max':4,'charsets':['lower'],'devices':'1','minutes':1})
        until(lambda:lib.jobs[jid]['state'] not in ('queued','recovering'))
        assert lib.jobs[jid]['state']=='ready',lib.jobs[jid]['message']
    print('PASS: fixed-prefix/suffix PDF mask',flush=True)
    source=root/'pause.pdf';make_pdf(source,'OutsideCandidateSet','AES-256')
    jid=lib.import_pdf(source.name,source.read_bytes())
    lib.start_recovery(jid,{'strategy':'mask','min':12,'max':12,'charsets':['digits'],'devices':'1','minutes':1})
    until(lambda:lib.jobs[jid].get('metrics',{}).get('speed',0)>0)
    time.sleep(2)
    lib.stop(jid)
    until(lambda:lib.jobs[jid]['state'] not in ('recovering','pausing'))
    assert lib.jobs[jid]['state']=='paused',lib.jobs[jid]
    checkpoint=has_checkpoint(lib.folder(jid))
    assert checkpoint, 'Hashcat did not create a restorable stage checkpoint'
    lib.start_recovery(jid,{},resume=True)
    until(lambda:lib.jobs[jid].get('metrics',{}).get('speed',0)>0)
    lib.stop(jid,cancel=True)
    until(lambda:lib.jobs[jid]['state'] not in ('recovering','pausing'))
    assert lib.jobs[jid]['state']=='cancelled',lib.jobs[jid]
    print(json.dumps({'pause':True,'resume':True,'cancel':True,'restore_checkpoint':checkpoint}),flush=True)
finally:
    lib.close()
