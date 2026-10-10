"""Opt-in Langfuse. Default payloads contain only allowlisted operational metadata."""
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
metrics=ContextVar('model_metrics',default=None)
prompt_version_context=ContextVar('prompt_version',default='engineering-v1')

@contextmanager
def observe(stage, model=None, prompt_version='engineering-v1', raw=None):
    start=time.perf_counter(); span=None; cm=None
    if os.getenv('LANGFUSE_ENABLED','false')=='true':
        try:
            from langfuse import get_client
            cm=get_client().start_as_current_observation(name=stage,as_type='generation' if model else 'span',
                model=model,metadata={'prompt_version':prompt_version})
            span=cm.__enter__()
            if os.getenv('TRACE_RAW_CONTENT','false')=='true' and raw is not None: span.update(input=raw)
        except Exception: span=None
    details={'stage':stage,'model':model,'prompt_version':prompt_version,'retries':0,'validation_failed':False}
    try: yield details
    except Exception as error:
        from backend.security import InvalidOutput
        details['paused']=type(error).__name__=='GraphInterrupt'
        details['failed']=not details['paused']
        details['validation_failed']=details['validation_failed'] or isinstance(error,InvalidOutput)
        raise
    finally:
        details['latency_ms']=(time.perf_counter()-start)*1000
        values=metrics.get()
        if values is not None: values.append(details.copy())
        if span:
            try:
                span.update(metadata=details,usage_details=details.get('tokens'))
                cm.__exit__(None,None,None)
            except Exception: pass  # Telemetry cannot break drafting.
