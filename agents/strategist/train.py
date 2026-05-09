"""
Kairos X — Robust RL Trainer.
Uses a simplified policy wrapper for ONNX compatibility.
"""

import os
import sys
import torch
import torch.nn as nn
from pathlib import Path
from stable_baselines3 import PPO

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.strategist.env import KairosTradingEnv

class OnnxablePolicy(nn.Module):
    def __init__(self, extractor, action_net, value_net):
        super().__init__()
        self.extractor = extractor
        self.action_net = action_net
        self.value_net = value_net

    def forward(self, observation):
        # Extract features
        features = self.extractor(observation)
        # Get action logits
        action_logits = self.action_net(features)
        # Get value estimate (optional but often exported)
        value = self.value_net(features)
        return action_logits, value

def train_and_export():
    print("--- Kairos X: Training RL Strategist (PPO) ---")
    
    env = KairosTradingEnv()
    model = PPO("MlpPolicy", env, verbose=1)
    
    print("Starting training for 20,000 steps (shortened for speed)...")
    model.learn(total_timesteps=20000)
    
    os.makedirs("models", exist_ok=True)
    model.save("models/kairos_ppo_strategist")
    
    print("Exporting to ONNX...")
    
    # Extract components from SB3 policy
    policy = model.policy.to("cpu")
    
    onnxable_model = OnnxablePolicy(
        policy.features_extractor,
        policy.action_net,
        policy.value_net
    )
    
    observation_size = env.observation_space.shape
    dummy_input = torch.randn(1, *observation_size)
    
    torch.onnx.export(
        onnxable_model,
        dummy_input,
        "models/strategist.onnx",
        export_params=True,
        opset_version=12,
        input_names=['input'],
        output_names=['action_logits', 'value'],
        dynamic_axes={'input': {0: 'batch_size'}, 'action_logits': {0: 'batch_size'}, 'value': {0: 'batch_size'}}
    )
    
    print("Successfully exported to models/strategist.onnx")

if __name__ == "__main__":
    train_and_export()
