from pikkabpe.train import training_guidance


def test_three_photos_are_one_class():
    rows=[{'barcode':'TX-E','session':'home-1'} for _ in range(3)]
    message=training_guidance(rows)
    assert '3 фото одного товара' in message
    assert 'второго товара' in message


def test_guidance_requests_new_capture_for_missing_products():
    rows=[{'barcode':code,'session':'home-1'} for code in ('A','B')]
    assert 'проверочная' in training_guidance(rows)
    rows.extend({'barcode':code,'session':'home-2'} for code in ('A','B'))
    assert training_guidance(rows)==''
