"""Presentation-only metadata for explicitly seeded fixtures; never grants access."""
import uuid

def ident(key): return str(uuid.uuid5(uuid.NAMESPACE_URL,'annha/demo/v1/'+key))
DEMO_HOMES={ident('home/'+key) for key in ('a','b')}
DEMO_CAMERAS={ident('camera/'+key+'/'+room) for key in ('a','b') for room in ('living','bedroom','entrance','yard')}
def demo_home(value): return str(value) in DEMO_HOMES
def demo_camera(value): return str(value) in DEMO_CAMERAS
