"""
Kairos X — Deeply Silent ONNX Exporter.
"""

import os
import sys
import torch
import torch.nn as nn
from pathlib import Path
from stable_baselines3 import PPO
import contextlib
import io

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

class OnnxablePolicy(nn.Module):
    def __init__(self, extractor, mlp_extractor, action_net, value_net):
        super().__init__()
        self.extractor = extractor
        self.mlp_extractor = mlp_extractor
        self.action_net = action_net
        self.value_net = value_net

    def forward(self, observation):
        features = self.extractor(observation)
        latent_pi, latent_vf = self.mlp_extractor(features)
        action_logits = self.action_net(latent_pi)
        value = self.value_net(latent_vf)
        return action_logits, value

def export_only():
    print("Loading model for export...")
    model = PPO.load("models/kairos_ppo_strategist")
    policy = model.policy.to("cpu")
    onnxable_model = OnnxablePolicy(
        policy.features_extractor,
        policy.mlp_extractor,
        policy.action_net,
        policy.value_net
    )
    onnxable_model.eval() # Important for inference
    
    dummy_input = torch.randn(1, 4)
    
    print("Exporting (deeply silent)...")
    
    # We use a string buffer to swallow all the emoji-laden logs from torch.onnx
    f = io.StringIO()
    try:
        with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
            torch.onnx.export(
                onnxable_model,
                dummy_input,
                "models/strategist.onnx",
                export_params=True,
                opset_version=15,
                input_names=['input'],
                output_names=['action_logits', 'value'],
                dynamic_axes={'input': {0: 'batch_size'}, 'action_logits': {0: 'batch_size'}, 'value': {0: 'batch_size'}}
            )
        print("Done! Check models/strategist.onnx")
    except Exception as e:
        # We don't print 'e' directly as it might contain emojis
        print("EXPORT FAILED with a runtime error.")
        # Try to save the log to a file for debugging
        with open("onnx_export_error.log", "w", encoding="utf-8") as log_file:
            log_file.write(str(e))
            log_file.write("\n\nFull Log:\n")
            log_file.write(f.getvalue())

if __name__ == "__main__":
    export_only()
