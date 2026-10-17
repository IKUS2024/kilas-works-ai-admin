"""Execution gate. A timeout/subprocess on the application host is not a sandbox."""


def capability():
    # No tenant-isolated execution service has been provisioned or authorized.
    # Neither an environment flag nor presence of bwrap grants that authority.
    return {'available':False,'reason':'isolated_execution_not_configured',
            'languages':[],'network':False,'production_host_execution':False}


def execute(*args,**kwargs):
    raise RuntimeError('isolated_execution_not_configured')
