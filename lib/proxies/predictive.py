import time
import torch
import torch.nn as nn
import torch.nn.functional as F

from .p_utils import *
from . import measures

import types
import copy


def no_op(self,x):
    return x


def copynet(self, bn):
    net = copy.deepcopy(self)
    if bn==False:
        for l in net.modules():
            if isinstance(l,nn.BatchNorm2d) or isinstance(l,nn.BatchNorm1d) :
                l.forward = types.MethodType(no_op, l)
    return net


def find_measures_arrays(net_orig, trainloader, dataload_info, device, measure_names=None, loss_fn=F.cross_entropy):
    if measure_names is None:
        measure_names = measures.available_measures

    dataload, num_imgs_or_batches, num_classes = dataload_info

    if not hasattr(net_orig,'get_prunable_copy'):
        net_orig.get_prunable_copy = types.MethodType(copynet, net_orig)

    #move to cpu to free up mem
    torch.cuda.empty_cache()
    net_orig = net_orig.cpu() 
    torch.cuda.empty_cache()

    #given 1 minibatch of data
    if dataload == 'random':
        inputs, targets = get_some_data(trainloader, num_batches=num_imgs_or_batches, device=device)
    elif dataload == 'grasp':
        inputs, targets = get_some_data_grasp(trainloader, num_classes, samples_per_class=num_imgs_or_batches, device=device)
    else:
        raise NotImplementedError(f'dataload {dataload} is not supported')

    done, ds = False, 1
    measure_values = {}
    measure_times  = {}

    while not done:
        try:
            for measure_name in measure_names:
                if measure_name not in measure_values:
                    start_time = time.time()
                    val = measures.calc_measure(measure_name, net_orig, device, inputs, targets, loss_fn=loss_fn, split_data=ds)
                    end_time   = time.time()
                    measure_values[measure_name] = val
                    measure_times[measure_name]  = end_time - start_time

            done = True
        except RuntimeError as e:
            if 'out of memory' in str(e):
                done=False
                if ds == inputs.shape[0]//2:
                    raise ValueError(f'Can\'t split data anymore, but still unable to run. Something is wrong') 
                ds += 1
                while inputs.shape[0] % ds != 0:
                    ds += 1
                torch.cuda.empty_cache()
                print(f'Caught CUDA OOM, retrying with data split into {ds} parts')
            else:
                raise e

    net_orig = net_orig.to(device).train()
    return measure_values, measure_times


def find_measures(net_orig,                  # neural network
                  dataloader,                # a data loader (typically for training data)
                  dataload_info,             # a tuple with (dataload_type = {random, grasp}, number_of_batches_for_random_or_images_per_class_for_grasp, number of classes)
                  device,                    # GPU/CPU device used
                  loss_fn=F.cross_entropy,   # loss function to use within the zero-cost metrics
                  measure_names=None,        # an array of measure names to compute, if left blank, all measures are computed by default
                  measures_arr=None):        # [not used] if the measures are already computed but need to be summarized, pass them here
    
    #Given a neural net
    #and some information about the input data (dataloader)
    #and loss function (loss_fn)
    #this function returns an array of zero-cost proxy metrics.

    if measures_arr is None:
        measures_arr, times = find_measures_arrays(net_orig, dataloader, dataload_info, device, loss_fn=loss_fn, measure_names=measure_names)

    measures = {}
    for k,v in measures_arr.items():
        measures[k] = v

    return measures, times
