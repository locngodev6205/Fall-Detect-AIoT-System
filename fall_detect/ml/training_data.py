"""Shared NumPy batches for Transformer, TCN and GRU."""
import math
from pathlib import Path

import numpy as np

from .dataset import jitter_coordinates
from .features import normalize_sequence
from .integrity import SPLITS, require_subset_approval, verify_dataset


class DataLoader:
    def __init__(self, root, split, *, batch_size=32, augment=False, shuffle=False, purpose=None, expected_sha256=None):
        if split not in SPLITS or batch_size < 1:
            raise ValueError('Unknown split or invalid batch size')
        if (augment or shuffle) and split != 'train':
            raise ValueError('Only the train split may be augmented or shuffled')
        self.root = Path(root)
        manifest = verify_dataset(self.root)
        if split == 'test':
            allowed = 'final_evaluation' if manifest['g3_eligible'] else 'research_evaluation'
            if purpose != allowed:
                raise ValueError(f'{manifest["mode"]} Test is reserved for {allowed}')
            if manifest['g3_eligible']:
                require_subset_approval(self.root, manifest)
        self.dataset_sha256 = manifest['dataset_sha256']
        if expected_sha256 is not None and expected_sha256 != self.dataset_sha256:
            raise ValueError('Dataset does not match the locked manifest SHA-256')
        self.seed = manifest['seed']
        self.batch_size = batch_size
        self.augment = augment
        self.shuffle = shuffle
        self.rows = tuple(row for row in manifest['windows'] if row['split'] == split)
        self.set_epoch(0)

    def set_epoch(self, epoch):
        self.epoch = epoch
        self.order = np.arange(len(self.rows))
        if self.shuffle:
            np.random.default_rng([self.seed, epoch]).shuffle(self.order)

    def __len__(self):
        return math.ceil(len(self.rows) / self.batch_size)

    def __getitem__(self, batch):
        if not 0 <= batch < len(self):
            raise IndexError(batch)
        samples, labels = [], []
        indices = self.order[batch * self.batch_size:(batch + 1) * self.batch_size]
        for i in indices:
            row = self.rows[i]
            raw = np.load(self.root / row['path'], allow_pickle=False)
            if self.augment:
                raw = jitter_coordinates(raw, np.random.default_rng([self.seed, self.epoch, int(i)]))
            samples.append(normalize_sequence(raw))
            labels.append(row['label'])
        return np.stack(samples), np.array(labels, dtype=np.int64)

    def __iter__(self):
        for batch in range(len(self)):
            yield self[batch]
