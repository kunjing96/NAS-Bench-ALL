import torch
import torch.nn as nn
from timm.utils import accuracy
import logging
import tqdm
from timm.utils.model import unwrap_model
import numpy as np

from lib.datasets import build_dataset
from lib.MetricLogger import MetricLogger
from estimation_strategies import _register
from estimation_strategies.Base import Base
from lib.nets.DARTS.net import Network
from lib.nets.NAG.model import NASNetworkCIFAR, NASNetworkImageNet


@_register
class StandardTraining(Base):

    def __init__(self, config, search_space):
        super(StandardTraining, self).__init__(config, search_space)

        self.device = torch.device(config.DEVICE)
        
        self.train_portion = config.TRAINPORTION

        dataset_train, self.n_classes = build_dataset(is_train=True, config=config)
        dataset_test, _ = build_dataset(is_train=False, config=config)
        num_train = len(dataset_train)
        indices = list(range(num_train))
        if self.train_portion < 1:
            split = int(np.floor(self.train_portion * num_train))
        else:
            split = num_train
        self.train_loader = torch.utils.data.DataLoader(
            dataset_train,
            batch_size=config.BATCHSIZE,
            sampler=torch.utils.data.sampler.SubsetRandomSampler(indices[:split]),
            pin_memory=config.PINMEM,
            num_workers=config.NUMWORKERS)
        if self.train_portion < 1:
            self.val_loader = torch.utils.data.DataLoader(
              dataset_train,
              batch_size=config.BATCHSIZE,
              sampler=torch.utils.data.sampler.SubsetRandomSampler(indices[split:num_train]),
              pin_memory=config.PINMEM,
              num_workers=config.NUMWORKERS)     
        else:
            self.val_loader = None
        self.test_loader = torch.utils.data.DataLoader(dataset_test,
            batch_size=config.BATCHSIZE,
            shuffle=False,
            num_workers=config.NUMWORKERS,
            pin_memory=config.PINMEM)
            
        self.criterion = nn.CrossEntropyLoss().to(self.device)

        shape = dataset_train.data.shape
        self.input_channels = 3 if len(shape) == 4 else 1
        assert shape[1] == shape[2], "not expected shape = {}".format(shape)
        self.input_size = shape[1]

    def train(self):
        metric_logger = MetricLogger(delimiter="  ")
        # header = 'Retrain'
        self.model.train()
        for _, (X, y) in enumerate(self.train_loader):
            X, y = X.to(self.device, non_blocking=True), y.to(self.device, non_blocking=True)

            self.optimizer.zero_grad()
            logits, aux_logits = self.model(X)
            loss = self.criterion(logits, y)
            if self.config.AUXWEIGHT > 0.:
                loss += self.config.AUXWEIGHT * self.criterion(aux_logits, y)
            loss.backward()
            # gradient clipping
            nn.utils.clip_grad_norm_(self.model.parameters(), self.config.GRAD_CLIP)
            self.optimizer.step()

            acc1, acc5 = accuracy(logits, y, topk=(1, 5))

            batch_size = X.size(0)
            metric_logger.meters['acc1'].update(acc1.item(), n=batch_size)
            metric_logger.meters['acc5'].update(acc5.item(), n=batch_size)

        return {k: meter.global_avg for k, meter in metric_logger.meters.items()}

    @torch.no_grad()
    def evaluate(self, model, data_loader):
        metric_logger = MetricLogger(delimiter="  ")
        # header = 'Val/Test:'

        model.eval()

        for X, y in tqdm.tqdm(data_loader):
            X, y = X.to(self.device, non_blocking=True), y.to(self.device, non_blocking=True)

            logits = model(X)
            if isinstance(logits, tuple):
                logits = logits[0]

            acc1, acc5 = accuracy(logits, y, topk=(1, 5))

            batch_size = X.size(0)
            metric_logger.meters['acc1'].update(acc1.item(), n=batch_size)
            metric_logger.meters['acc5'].update(acc5.item(), n=batch_size)

        return {k: meter.global_avg for k, meter in metric_logger.meters.items()}

    def retrain_and_eval(self, genotype):
        if getattr(self.search_space, 'model_cls', None) is not None:
            if self.search_space.model_cls is Network:
                self.model = self.search_space.model_cls(self.input_size, self.input_channels, 36, self.n_classes, 20, self.config.AUXWEIGHT>0, genotype).to(self.device)
            elif self.search_space.model_cls is NASNetworkCIFAR or self.search_space.model_cls is NASNetworkImageNet:
                layers = 6 if self.search_space.model_cls is NASNetworkCIFAR else 4
                channels = 36 if self.search_space.model_cls is NASNetworkCIFAR else 48
                keep_prob = 0.6 if self.search_space.model_cls is NASNetworkCIFAR else 1.0
                self.model = self.search_space.model_cls(self.n_classes, layers, channels, keep_prob, 1 - self.config.DROPPATHPROB, self.config.AUXWEIGHT>0, int(np.ceil(45000 / self.config.BATCHSIZE)) * self.config.EPOCHS, genotype).to(self.device)
        else:
            pass # TODO
        # weights optimizer
        self.optimizer = torch.optim.SGD(self.model.parameters(), self.config.LR, momentum=self.config.MOMENTUM, weight_decay=self.config.WEIGHTDECAY)
        self.lr_scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(self.optimizer, self.config.EPOCHS)
        model_module = unwrap_model(self.model)

        best_top1 = 0.
        best_val_res = None
        best_test_res = None
        # training loop
        for epoch in tqdm.tqdm(range(self.config.EPOCHS)):
            self.lr_scheduler.step()
            if hasattr(model_module, 'drop_path_prob') and self.config.DROPPATHPROB is not None:
                drop_prob = self.config.DROPPATHPROB * epoch / self.config.EPOCHS
                model_module.drop_path_prob(drop_prob)
            # training
            self.train()
            # validation
            test_res = self.evaluate(self.model, self.test_loader)
            if self.val_loader is not None:
                val_res = self.evaluate(self.model, self.val_loader)
            else:
                val_res = test_res
            if best_top1 < val_res['acc1']:
                best_top1 = val_res['acc1']
                best_val_res = val_res
                best_test_res = test_res
        return best_val_res, best_test_res

    def __call__(self, arch):
        logging.info("Sampled arch: {}".format(arch))
        val_res, test_res = self.retrain_and_eval(arch)
        logging.info("Score: {}\tPerformence: {}".format(val_res, test_res))
        return val_res['acc1'], test_res['acc1']
