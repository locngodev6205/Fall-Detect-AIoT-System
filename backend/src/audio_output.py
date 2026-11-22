"""Shared desired and observed audio-output state for both database adapters."""

def heartbeat_capabilities(payload):
    capabilities = dict(payload.capabilities)
    if payload.audio_output is not None:
        capabilities['audio_output'] = payload.audio_output.model_dump()
    return capabilities


def audio_output_state(payload, capabilities, desired_version, applied_version, online, config_error=None):
    actual = capabilities.get('audio_output') or {}
    desired = payload.get('audio_output') or actual.get('mode') or 'analog'
    desired_version, applied_version = desired_version or 0, applied_version or 0
    return {
        'mode': desired,
        'actual_mode': actual.get('mode'),
        'online': online,
        'ready': bool(online and actual.get('ready')),
        'switching': bool(desired_version > applied_version or actual.get('mode') != desired
                          or actual.get('version', 0) < desired_version),
        'error': actual.get('error') or '',
        'switch_error': config_error if desired_version > applied_version else None,
        'desired_version': desired_version,
        'applied_version': applied_version,
    }
