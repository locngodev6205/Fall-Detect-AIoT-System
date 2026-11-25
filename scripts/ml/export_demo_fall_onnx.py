"""Export the two frozen checkpoints and verify PyTorch/ONNX score parity.

Usage: PYTHONPATH=/path/to/pinned-upstream python export_demo_fall_onnx.py DATA OUTPUT
"""
import hashlib,sys
from pathlib import Path
import numpy as np
import onnxruntime as ort
import torch
from src.model import CTRGCN

ROOT = Path(sys.argv[1])
OUTPUT = Path(sys.argv[2])
OUTPUT.mkdir(exist_ok=True)

torch.set_num_threads(2)
class Graph(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.net=CTRGCN(base_channels=8)
    def forward(self, x):
        return self.net(x.reshape(1,20,17,3).permute(0,3,1,2).unsqueeze(-1)).sigmoid()
class GRU(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.temporal=torch.nn.GRU(51,32,batch_first=True)
        self.out=torch.nn.Linear(32,1)
    def forward(self,x):
        return self.out(self.temporal(x)[0][:,-1]).squeeze(-1).sigmoid()
for name, model, path, sha in [
 ('ctr',Graph(),ROOT/'accuracy-pose-v1/multisource-local/multi-2026/best.pt','f0c8f4c6512195626b4e9f2a09bbd9ce78be3bb7661dbcd6fbf05b003f52e308'),
 ('gru',GRU(),ROOT/'pr04.1/controlled/full-E4-42.pt','5ef559faee3374f57e240b389ad413c336449f85866b4ef357581abef13bb7ac')]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError(f"Unexpected checkpoint SHA-256: {path.name}")
    weights=torch.load(path,map_location='cpu',weights_only=True)
    (model.net if name=='ctr' else model).load_state_dict(weights['state_dict'] if name=='ctr' else weights)
    model.eval()
    out = OUTPUT / (name + '.onnx')
    if out.exists():
        raise FileExistsError(out)
    x=torch.zeros(1,20,51)
    torch.onnx.export(model,x,out,input_names=['window'],output_names=['score'],opset_version=17,dynamo=False)
    opts=ort.SessionOptions(); opts.intra_op_num_threads=2
    rt=ort.InferenceSession(str(out),sess_options=opts,providers=['CPUExecutionProvider'])
    rng=np.random.default_rng(42)
    windows=[rng.normal(size=(1,20,51)).astype('float32') for _ in range(32)]
    windows+= [rng.normal(size=(1,20,51)).astype('float32') for _ in range(4)]
    for i,window in enumerate(windows[-4:]): window[:,7:7+i]=0
    with torch.inference_mode():
        error=max(abs(float(rt.run(None,{'window':w})[0].item())-float(model(torch.from_numpy(w)).item())) for w in windows)
    if error >= 1e-4:
        raise ValueError(f"ONNX score parity failed: {error}")
    print(name,'parameters',sum(p.numel() for p in model.parameters()),'sha',hashlib.sha256(out.read_bytes()).hexdigest(),'max_abs_error',error,flush=True)
