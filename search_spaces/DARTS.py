import torch.nn as nn

from search_spaces import _register
from search_spaces.Base import Base
from lib.models.DARTS.genotypes import PRIMITIVES
from lib.models.DARTS.search_net import SearchCNNController


@_register
class DARTS(Base):

    def __init__(self, config):
        super(DARTS, self).__init__(config)
        self.choices = PRIMITIVES
        net_crit = nn.CrossEntropyLoss()
        self.model = SearchCNNController(3, 16, 10, 8, net_crit)
