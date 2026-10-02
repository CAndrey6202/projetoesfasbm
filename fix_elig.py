
with open("backend/services/justica_service.py", "r", encoding="utf-8") as f:
    text = f.read()

old_func = """    @staticmethod
    def verificar_elegibilidade_punicao(
        processo, dt_inicio_2_ciclo, dt_limite_atitudinal
    ):
        data_fato = JusticaService._ensure_datetime(processo.data_ocorrencia)
        dt_limite = JusticaService._ensure_datetime(dt_limite_atitudinal)
        if not data_fato:
            return False
        if data_fato > dt_limite:
            return False"""

new_func = """    @staticmethod
    def verificar_elegibilidade_punicao(
        processo, dt_inicio_2_ciclo, dt_limite_atitudinal
    ):
        data_fato = JusticaService._ensure_datetime(processo.data_ocorrencia)
        if not data_fato:
            return False
        if dt_limite_atitudinal:
            dt_limite = JusticaService._ensure_datetime(dt_limite_atitudinal)
            if data_fato > dt_limite:
                return False"""

if old_func in text:
    text = text.replace(old_func, new_func)
    with open("backend/services/justica_service.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("Replaced eligibilidade")
else:
    print("Not found")

