"""
Kairos X — Trading Gymnasium Environment.
Defines the observation space (LOB indicators) and rewards for RL training.
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np

class KairosTradingEnv(gym.Env):
    """
    Custom Environment for training the PPO Strategist.
    
    Observations:
        [order_imbalance, momentum_normalized, sentiment, spread_pct]
    Actions:
        0: HOLD
        1: BUY (Enter/Increase Long)
        2: SELL (Enter/Increase Short)
    """
    def __init__(self):
        super(KairosTradingEnv, self).__init__()
        
        # Action space: 0=Hold, 1=Buy, 2=Sell
        self.action_space = spaces.Discrete(3)
        
        # Observation space: 4 continuous values normalized roughly to [-1, 1]
        self.observation_space = spaces.Box(
            low=-1.0, high=1.0, shape=(4,), dtype=np.float32
        )
        
        self.state = np.zeros(4, dtype=np.float32)
        self.position = 0 # 0=Flat, 1=Long, -1=Short
        self.entry_price = 0.0
        self.current_step = 0

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.state = np.random.uniform(-0.1, 0.1, size=(4,)).astype(np.float32)
        self.position = 0
        self.current_step = 0
        return self.state, {}

    def step(self, action):
        self.current_step += 1
        
        # Simulate next state (random walk for training stability)
        self.state += np.random.normal(0, 0.1, size=(4,)).astype(np.float32)
        self.state = np.clip(self.state, -1.0, 1.0)
        
        # Extract mid_price from a simulated walk (relative to 100)
        price_change = self.state[1] * 0.5 # use momentum as price change proxy
        reward = 0.0
        
        if action == 1: # BUY
            if self.position == -1: # Close short
                reward += (self.entry_price - 100.0) # simplified
                self.position = 0
            elif self.position == 0: # Open long
                self.position = 1
                self.entry_price = 100.0
        
        elif action == 2: # SELL
            if self.position == 1: # Close long
                reward += (100.0 - self.entry_price)
                self.position = 0
            elif self.position == 0: # Open short
                self.position = -1
                self.entry_price = 100.0
        
        # Unrealized PnL reward component
        if self.position == 1:
            reward += price_change
        elif self.position == -1:
            reward -= price_change
            
        # Penalty for excessive trading
        if action != 0:
            reward -= 0.01
            
        terminated = self.current_step >= 1000
        truncated = False
        
        return self.state, reward, terminated, truncated, {}
