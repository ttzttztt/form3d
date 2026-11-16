# -*- coding: utf-8 -*-
"""Synthetic safety regression tests, not model quality measurements."""
import unittest
import numpy as np
from PIL import Image,ImageDraw
from input_preflight_rules import mask_metrics,remove_dimension_components,evaluate
from local3d_preprocess import remove_product_background

class InputRulesTests(unittest.TestCase):
    def fixture(self):
        image=Image.new('RGBA',(240,200),(255,255,255,0))
        draw=ImageDraw.Draw(image);draw.rectangle((30,20,140,180),fill='#446633')
        draw.rectangle((175,140,180,155),fill='black')
        return image

    def test_only_detached_dimension_alpha_is_removed(self):
        image=self.fixture();before=np.array(image)
        polygon=[[170,135],[200,135],[200,160],[170,160]]
        result,mask,records=remove_dimension_components(image,[(polygon,'5 in',.99)])
        after=np.asarray(result)
        self.assertEqual(records[0]['action'],'removed_detached_dimension')
        self.assertEqual(result.getpixel((177,147))[3],0)
        self.assertTrue(np.array_equal(before[:,:,:3],after[:,:,:3]))
        self.assertTrue(np.array_equal(before[20:181,30:141],after[20:181,30:141]))
        self.assertGreater(np.asarray(mask).sum(),0)

    def test_logo_numeric_model_and_low_confidence_are_preserved(self):
        for text,score in [('ACME',.99),('3M',.99),('Model 5',.99),('5 in',.3)]:
            image=self.fixture()
            result,_,_=remove_dimension_components(image,[([[170,135],[200,135],[200,160],[170,160]],text,score)])
            self.assertEqual(result.tobytes(),image.tobytes())

    def test_measurement_overlapping_main_product_is_protected(self):
        image=self.fixture()
        result,_,records=remove_dimension_components(image,[([[100,80],[145,80],[145,105],[100,105]],'12cm',.99)])
        self.assertEqual(result.tobytes(),image.tobytes())
        self.assertEqual(records[0]['action'],'preserved_product_overlap')

    def test_disconnected_leaves_are_not_removed_without_text(self):
        image=self.fixture()
        result,_,_=remove_dimension_components(image,[])
        self.assertEqual(result.tobytes(),image.tobytes())

    def test_fragmented_mask_is_blocked(self):
        image=Image.new('RGBA',(400,400),(0,0,0,0));data=np.array(image)
        data[::10,::10]=[0,0,0,255];image=Image.fromarray(data)
        decision=evaluate(mask_metrics(image),image.size,[])
        self.assertEqual(decision['status'],'blocked')
        self.assertIn('fragmented_mask',[r['code'] for r in decision['reasons']])

    def test_structural_holes_alone_do_not_block(self):
        image=self.fixture();draw=ImageDraw.Draw(image)
        draw.rectangle((45,35,125,85),fill=(0,0,0,0))
        self.assertEqual(evaluate(mask_metrics(image),image.size,[])['status'],'pass')

    def test_small_native_input_cannot_be_fixed_by_upscaling(self):
        image=Image.new('RGBA',(500,500),'gray')
        decision=evaluate(mask_metrics(image),(58,62),[])
        self.assertEqual(decision['reasons'][0]['code'],'insufficient_native_pixels')

    def test_clutter_blocks_even_a_continuous_mask(self):
        image=Image.new('RGBA',(240,200),'gray')
        decision=evaluate(mask_metrics(image),image.size,[{'requires_attention':True,'label':'猫'}])
        self.assertEqual(decision['reasons'][0]['code'],'foreground_clutter')

    def test_white_hint_keeps_tight_crop_out_of_u2net(self):
        image=Image.new('RGBA',(240,200),'white')
        ImageDraw.Draw(image).rectangle((0,30,239,170),fill='#555555')
        result,method=remove_product_background(image,None,white_background_rgb=[255,255,255])
        self.assertEqual(method,'white_background_connected_components')
        self.assertEqual(result.getpixel((100,100))[3],255)
        self.assertEqual(result.getpixel((100,10))[3],0)

    def test_dimension_bracket_is_removed_with_nearby_unit_text(self):
        image=self.fixture();draw=ImageDraw.Draw(image)
        draw.line([(160,110),(166,110),(166,180),(160,180)],fill='black',width=1)
        result,_,records=remove_dimension_components(image,[([[172,136],[198,136],[198,157],[172,157]],'5in',.99)])
        self.assertEqual(result.getpixel((166,120))[3],0)
        self.assertEqual(result.getpixel((70,120))[3],255)
        self.assertEqual(records[0]['removed_dimension_brackets'],1)

    def test_unticked_thin_part_is_preserved(self):
        image=self.fixture();ImageDraw.Draw(image).line([(165,110),(165,180)],fill='black',width=1)
        result,_,_=remove_dimension_components(image,[([[172,136],[198,136],[198,157],[172,157]],'5in',.99)])
        self.assertEqual(result.getpixel((165,120))[3],255)

if __name__=='__main__':unittest.main(verbosity=2)
