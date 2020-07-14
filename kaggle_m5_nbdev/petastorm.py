# AUTOGENERATED! DO NOT EDIT! File to edit: 01_petastorm.ipynb (unless otherwise specified).

__all__ = ['ParquetIterableDataset']

# Cell
class ParquetIterableDataset(IterableDataset):
    def __init__(self, filename, log, rex=None):
        super().__init__()
        self._filename_param = filename
        self.rex_param = rex
        self.log = log
        # self.patch = PetastormLeakyDescriptorsPatch()
        # self.patch.patch_leaking_fd(log)
        self.filename_param = filename
        self.filename = _init_filenames(log, filename, rex)

    def _init_petaloader(self):
        def _transform_row(df_batch):
            return df_batch

        transform = TransformSpec(_transform_row, removed_fields=['cat_id', 'store_id', 'state_id'])
        reader = make_batch_reader(self.filename,
                 schema_fields=['id', 'item_id', 'dept_id', 'cat_id', 'day_id',
               'sales', 'day_date_str', 'month_id', 'date', 'wm_yr_wk',
               'snap_flag', 'sell_price', 'sales_dollars', 'store_id', 'state_id'],
                workers_count=1
                #,transform_spec = transform
        )
        return PetaDataLoader(reader=reader, batch_size=128, shuffling_queue_capacity=100000)

    def __len__(self):
        return 1913*30490 # can be arbitrary large value to prevent WARN logs, seem to be ignored anyway

    def __iter__(self):
        self.log.debug(f"Iterator created on {self._filename_param}")
        worker_info = torch.utils.data.get_worker_info()
        if worker_info is None:
            count_cells = 0
            count_batches = 0
            with self._init_petaloader() as loader:
                # self.patch.patch_loader(loader)
                for batch in loader:
                    count_batches += 1
                    # TODO: propagate petaloader's batches without breaking them into individual items
                    for idx in range(len(batch['sell_price'])):
                        price         = batch['sell_price'][idx]
                        sales_dollars = batch['sales_dollars'][idx] if ('sales_dollars' in batch) else -1.
                        price_is_nan = math.isnan(price)
                        # TODO: this starts to look like feature extraction, doesn't belong here
                        price_or_zero = 0. if price_is_nan else price
                        count_cells += 1
                        # float32 needed for pytorch downstream
                        yield {'features': tensor([price_or_zero, price_is_nan], dtype=torch.float32),
                               'targets': tensor([sales_dollars])}

            self.log.debug(f'Done iterating: {count_batches} batches / ({count_cells} cells) ')
        else:
            raise ValueError("Not implemented for multithreading")