from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import torch
import torch.nn.quantized.functional as qF
from torch.nn.quantized.modules import Conv2d
from torch.nn.quantized.modules.conv import _conv_output_shape

import numpy as np
from common_utils import TestCase, run_tests

from hypothesis import assume, given
from hypothesis import strategies as st
from hypothesis_utils import qtensors_conv

def _quantize(x, scale, zero_point, qmin=0, qmax=255):
    """Quantizes a numpy array."""
    qx = np.round(x / scale + zero_point)
    qx = np.clip(qx, qmin, qmax).astype(np.uint8)
    return qx

class ModuleAPITest(TestCase):
    def test_functional_api(self):
        X = torch.arange(-5, 5, dtype=torch.float)
        scale = 2.0
        zero_point = 1
        Y = X.numpy().copy()
        Y[Y < 0] = 0
        qY = _quantize(Y, scale, zero_point)
        qX = X.quantize_linear(scale=scale, zero_point=zero_point, dtype=torch.quint8)
        qY_hat = F.relu(qX)
        np.testing.assert_equal(qY, qY_hat.int_repr())

    @given(Q=qtensors_conv(min_batch=1, max_batch=3,
                           min_in_channels=1, max_in_channels=5,
                           min_out_channels=1, max_out_channels=5,
                           H_range=(6, 12), W_range=(6, 12),
                           kH_range=(3, 5), kW_range=(3, 5),
                           dtypes=((torch.quint8, np.uint8, 0),)),
           padH=st.integers(1, 3), padW=st.integers(1, 3),
           sH=st.integers(1, 3), sW=st.integers(1, 3))
    def test_conv_api(self, Q, padH, padW, sH, sW):
        """Tests the correctness of the conv module.

        The correctness is defined against the functional implementation.
        """
        ref_op = qF.conv2d

        # Not implemented parameters
        dH, dW = 1, 1
        o_padH, o_padW = 0, 0
        groups = 1

        # Random iunputs
        X, (scale, zero_point), (qmin, qmax), (torch_type, np_type) = Q
        (inputs, filters, bias) = X

        iC, oC = inputs.shape[1], filters.shape[0]
        assume(iC % groups == 0)
        iH, iW = inputs.shape[2:]
        kH, kW = filters.shape[2:]
        assume(kH // 2 >= padH)
        assume(kW // 2 >= padW)
        oH = _conv_output_shape(iH, kH, padH, sH, dH, o_padH)
        assume(oH > 0)
        oW = _conv_output_shape(iW, kW, padW, sW, dW, o_padW)
        assume(oW > 0)

        inputs = torch.from_numpy(inputs).to(torch.float)
        filters = torch.from_numpy(filters).to(torch.float)
        bias = torch.from_numpy(bias).to(torch.float)

        kernel_size = (kH, kW)
        stride = (sH, sW)
        i_padding = (padH, padW)
        o_padding = (o_padH, o_padW)
        dilation = (dH, dW)

        i_NHWC = inputs.permute([0, 2, 3, 1]).contiguous()
        w_RSCK = filters.permute([2, 3, 1, 0]).contiguous()

        q_inputs = torch.quantize_linear(i_NHWC, scale, zero_point, torch.quint8)
        q_filters = torch.quantize_linear(w_RSCK, scale, zero_point, torch.qint8)
        q_bias = torch.quantize_linear(bias, scale, zero_point, torch.qint32)

        # Results check
        print("TEST 1")
        conv_2d = Conv2d(weight=q_filters, bias=q_bias,
                         scale=scale, zero_point=zero_point,
                         dtype=torch_type,
                         stride=stride, padding=i_padding,
                         dilation=dilation, groups=groups,
                         padding_mode='zeros')

        try:
            print("TEST 2")
            ref_result = qF.conv2d(q_inputs, q_filters, bias=q_bias,
                                   scale=scale, zero_point=zero_point,
                                   stride=stride, padding=i_padding,
                                   dilation=dilation, groups=groups,
                                   prepacked=False, dtype=torch_type)
            print("TEST 3")
        except Exception as e:
            # We should be throwing the same error.
            print("TEST 4")
            np.testing.assert_raises_regex(Exception, str(e),
                                           conv_2d, q_inputs)
            print("TEST 5")
        else:
            print("TEST 6")
            q_result = conv_2d(q_inputs)
            print("TEST 7")
            np.testing.assert_equal(ref_result.int_repr().numpy(),
                                    q_result.int_repr().numpy())
            print("TEST 8")

if __name__ == '__main__':
    run_tests()
