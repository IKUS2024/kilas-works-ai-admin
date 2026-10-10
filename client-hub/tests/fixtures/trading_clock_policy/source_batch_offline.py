"""Synthetic-only source-state adapter. No broker activation."""
from clock_batch_offline import qualify_batch, policy, require
from decimal import Decimal

class BatchFixtureSource(policy.ReadOnlyFixtureSource):
    def __init__(self,*,profile,server):
        super().__init__(profile=profile,server=server)
        self.batch_session=None

    def observe_batch(self,sample,candle_times,batch):
        self.validated=None;self.clock_deadline=None;self.clock_decision=None
        try:
            require(self.connected, 'Disconnected source.')
            require(type(self.profile) is policy.BrokerTimeProfile,'Explicit configured profile required.')
            windows=self.profile.validated_windows()
            require(self.server=='XMGlobal-MT5 10' and len(windows)==1 and windows[0][2]==10800
                    and (windows[0][1]-windows[0][0]).total_seconds()<=1200,'Original session profile gate.')
            fields={'kind','time','time_msc','acquired_start_utc','acquired_end_utc','acquired_start_mono_ns','acquired_end_mono_ns'}
            require(type(sample) is dict and set(sample)==fields and sample['kind']=='TEST_FIXTURE','Synthetic fixture only.')
            for k in ('acquired_start_utc','acquired_end_utc','acquired_start_mono_ns','acquired_end_mono_ns'):
                require(sample[k]==batch[k],'Sample does not belong to batch.')
            q=qualify_batch(batch)
            if self.batch_session is None:self.batch_session=batch['session_id']
            require(self.batch_session==batch['session_id'],'Session changed.')
            clock=policy.SameCycleClock(Decimal(q['offset_seconds']),Decimal(q['uncertainty_seconds']),q['expires_mono_ns'],q['evidence_sha256'])
            decision=batch['decision_utc'];dm=batch['decision_mono_ns']
            require(windows[0][0]<=clock.corrected(decision)<windows[0][1],'Expired session profile.')
            require(clock.evidence_id not in self.used_cycles and len(self.used_cycles)<2,'Reused cycle or more than two observations.')
            self.used_cycles.add(clock.evidence_id)
            event=policy.utc(policy.normalize(sample['time'],sample['time_msc'],profile=self.profile,server=self.server,api='symbol_info_tick')['normalized_time_utc'])
            age=policy.seconds(clock.corrected(decision)-event)
            require(Decimal(0)<=age+clock.uncertainty_seconds<=5,'Five-second worst-case source freshness failed.')
            corrected={k:v for k,v in sample.items() if k not in ('acquired_start_mono_ns','acquired_end_mono_ns')}
            for k in ('acquired_start_utc','acquired_end_utc'):corrected[k]=clock.corrected(sample[k]).isoformat()
            result=self.observe(corrected,candle_times,clock_verified=True,
              clock_uncertainty_ms=int((clock.uncertainty_seconds*1000).to_integral_value(rounding='ROUND_CEILING')),
              clock_evidence_ref=clock.evidence_id,_same_cycle=True)
            if result['status']!='UNAVAILABLE':
                result.update(clock_assurance='UNAUTHENTICATED_OPERATIONAL_PAPER_ONLY',clock_offset_seconds=str(clock.offset_seconds),
                              raw_acquired_start_utc=sample['acquired_start_utc'],raw_acquired_end_utc=sample['acquired_end_utc'],
                              clock_expires_mono_ns=clock.expires_mono_ns)
            if result['status']=='READ_ONLY_VALIDATED_FIXTURE':
                self.clock_deadline=clock.expires_mono_ns;self.clock_decision=(dm,policy.utc(decision),clock)
            result.update(synthetic=True,policy_replay_only=True,runtime_eligible=False,broker_execution_allowed=False,
                          producer_acceptance='NOT_IMPLEMENTED')
            if result['status']=='UNAVAILABLE':self.connected=False
            return result
        except (ValueError,TypeError,KeyError,ArithmeticError):
            self.connected=False;self.previous=None;self.validated=None;self.clock_deadline=None;self.clock_decision=None
            return dict(status='UNAVAILABLE',synthetic=True,ai_analysis=False,paper_execution=False,
                        runtime_eligible=False,broker_execution_allowed=False,reason='Batch/source checks failed. New explicit source required.')
