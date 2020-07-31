# AUTOGENERATED! DO NOT EDIT! File to edit: 02_pipeline.ipynb (unless otherwise specified).

__all__ = ['prepare_data_on_disk', 'load_encoders', 'encode', 'prepare_test_data_on_disk', 'setup_data_loaders', 'Net',
           'MyLoss', 'do_train']

# Cell

from ..core import read_series_sample, melt_sales_series, extract_day_ids, join_w_calendar, join_w_prices
from ..core import to_parquet, get_submission_template_melt
from ..petastorm import ParquetIterableDataset
import os

def prepare_data_on_disk(log, n_sample_series, processed_dir, raw_dir, force_data_prep):
    expected_path = f'{processed_dir}/sales_series_melt.parquet'
    if os.path.exists(expected_path) and not force_data_prep:
        log.info(f'Found parquet file ({expected_path})- skipping the prep')
        return

    log.info(f'Not found parquet file ({expected_path}) - preparing the data')

    sales_series = read_series_sample(log, n_sample_series)
    sales_series = melt_sales_series(sales_series)
    sales_series = extract_day_ids(sales_series)
    sales_series = join_w_calendar(sales_series, raw_dir)
    sales_series = join_w_prices(sales_series, raw_dir).persist()
    to_parquet(sales_series, 'sales_series_melt.parquet', processed_dir, log)

# Cell
# export
from sklearn.preprocessing import LabelEncoder
import dask.dataframe as dd
import numpy as np

def load_encoders(processed):
    def _load(fn):
        l = LabelEncoder()
        l.classes_ = np.load(f'{processed}/{fn}', allow_pickle=True)
        return l

    encoders_paths = filter(lambda p: p.endswith('.npy'), os.listdir(processed))
    encoders = {fn[:-len('.npy')]:_load(fn) for fn in encoders_paths}

    return encoders

def encode(log, me, processed):
    encoders = load_encoders(processed)
    continuous_cols = ['sell_price']

    for col in me.columns:
        dtype_str = str(me[col].dtype)
        if col in continuous_cols:
            log.debug(f"Encoding {col} ({dtype_str}) as float32 just in case for pytorch")
            me[col] = me[col].astype('float32')
            continue

        log.debug(f"Encoding {col} ({dtype_str}) as categorical ")

        unlabelable = ~me[col].isin(encoders[col].classes_)
        unlabelable_count = unlabelable.sum()
        if unlabelable_count > 0:
            default_label = encoders[col].classes_[0]
            log.warning(f"{unlabelable_count} entries for {col} can't be labeled. Defaulting to {default_label} e.g.\n {me[unlabelable][col][:3].values}")
            me.loc[unlabelable, col] = default_label

        me[col] = encoders[col].transform(me[col])

    return me

# Cell
def prepare_test_data_on_disk(log, raw, processed, force_data_prep):
    expected_path = f'{processed}/test_series_melt.parquet'
    if os.path.exists(expected_path) and not force_data_prep:
        log.info(f'Found parquet file ({expected_path})- skipping the prep')
        return

    template = get_submission_template_melt(raw)
    test_data = encode(log, template, processed)
    to_parquet(test_data, 'test_series_melt.parquet', processed, log)

# Cell
from torch.utils.data import TensorDataset, DataLoader as TorchDataLoader, IterableDataset
from collections import OrderedDict

def setup_data_loaders(processed, log):
    batch = 128

    train_ds = ParquetIterableDataset(f'file:{processed}/sales_series_melt.parquet', log, '.*part.(?!1).*')
    valid_ds = ParquetIterableDataset(f'file:{processed}/sales_series_melt.parquet', log, '.*part.1.*')
    test_ds  = ParquetIterableDataset(f'file:{processed}/test_series_melt.parquet', log)

    train_dl = TorchDataLoader(train_ds, batch_size=batch, shuffle=False, num_workers=0, drop_last=False)
    valid_dl = TorchDataLoader(valid_ds, batch_size=batch, shuffle=False, num_workers=0, drop_last=False)
    test_dl  = TorchDataLoader(test_ds,  batch_size=batch, shuffle=False, num_workers=0, drop_last=False)

    data = OrderedDict()
    data["train"] = train_dl
    data["valid"] = valid_dl
    data["test"]  = test_dl

    return data

# Cell
import torch
from torch import nn
import torch.nn.functional as F

from catalyst.dl import SupervisedRunner
from catalyst.utils import set_global_seed

class Net(nn.Sequential):
    def __init__(self, num_features):
        layers = []
        layer_dims = [num_features, 200,200,20,20,1]
        for in_features, out_features in zip(layer_dims[:-1], layer_dims[1:]):
            l = nn.Linear(in_features, out_features)
            # Note to self: loss @ init is quite important!
            torch.nn.init.xavier_uniform_(l.weight)
            torch.nn.init.zeros_(l.bias)

            layers.append(l)
            layers.append(nn.ReLU())
        super(Net, self).__init__(*layers)

class MyLoss(nn.MSELoss):
    def __init__(self):
        super(MyLoss, self).__init__()

    def forward(self, inp, target):
        return super().forward(inp, target)

def do_train(data, log, log_dir):
    model = Net(num_features = 2)
    runner = SupervisedRunner()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
    criterion = MyLoss()

    log_batch(model, data, log, "init")

    log.debug("Starting training")
    runner.train(
        model=model,
        criterion=criterion,
        optimizer=optimizer,
        loaders=data,
        logdir=f"{log_dir}/run",
        load_best_on_end=True,
        num_epochs=1)

    log_batch(model, data, log, "exit")