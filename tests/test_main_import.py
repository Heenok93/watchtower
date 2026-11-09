def test_main_module_imports():
    import main

    assert callable(main.main)
    assert callable(main.backup_and_reset_database)