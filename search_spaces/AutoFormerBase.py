from search_spaces import _register
from search_spaces.AutoFormerTiny import AutoFormerTiny
from lib.nets.AutoFormer import Vision_TransformerSuper


@_register
class AutoFormerBase(AutoFormerTiny):

    def __init__(self, config):
        super(AutoFormerTiny, self).__init__(config)
        self.choices = {'num_heads': [9, 10], 'mlp_ratio': [3.0, 3.5, 4.0], 'embed_dim': [528, 576, 624] , 'depth': [14, 15, 16]}
        self.model = Vision_TransformerSuper(
                        img_size=224,
                        patch_size=16,
                        embed_dim=max(self.choices['embed_dim']), depth=max(self.choices['depth']),
                        num_heads=max(self.choices['num_heads']),mlp_ratio=max(self.choices['mlp_ratio']),
                        qkv_bias=True, drop_rate=0.0,
                        drop_path_rate=0.1,
                        gp=True,
                        num_classes=1000,
                        max_relative_position=14,
                        relative_position=True,
                        change_qkv=True, abs_pos=True
                    )
