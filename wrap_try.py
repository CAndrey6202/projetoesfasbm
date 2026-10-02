
with open("backend/controllers/justica_controller.py", "r", encoding="utf-8") as f:
    text = f.read()

old_block = """    processos_ativos = db.session.scalars(select(ProcessoDisciplina).where(ProcessoDisciplina.aluno_id == int(aluno_id), ProcessoDisciplina.status == StatusProcesso.FINALIZADO.value)).all()
    dt_inicio, dt_limite = JusticaService.get_datas_limites(db.session.get(Aluno, int(aluno_id)).turma_id)
    mapa_vinculos = {}

    for p in processos_ativos:
        if JusticaService.verificar_elegibilidade_punicao(p, dt_inicio, dt_limite):
            attr_idx = request.form.get(f'vinculo_infracao_{p.id}')
            if not attr_idx:
                flash(f"ERRO: A puni\\xc3\\xa7\\xc3\\xa3o (ID {p.id}) deve ser vinculada a um atributo.", "danger")
                return redirect(url_for('justica.fada_boletim'))
            mapa_vinculos[str(p.id)] = attr_idx

    limites_calculados, erro_limite = JusticaService.calcular_limites_fada(int(aluno_id), mapa_vinculos)
    if erro_limite:
        flash(f"Erro de Valida\\xc3\\xa7\\xc3\\xa3o: {erro_limite}", "danger"); return redirect(url_for('justica.fada_boletim'))

    notas_float = []
    for i, n_str in enumerate(notas):
        try:
            val = float(n_str)
            teto = limites_calculados[i]
            if val > (teto + 0.01):
                flash(f"ERRO no Atributo {i+1}: Nota {val} excede o limite de {teto:.2f}.", "danger"); return redirect(url_for('justica.fada_boletim'))
            notas_float.append(val)
        except ValueError:
            flash("Nota inv\\xc3\\xa1lida.", "danger"); return redirect(url_for('justica.fada_boletim'))

    try:"""

new_block = """    try:
        processos_ativos = db.session.scalars(select(ProcessoDisciplina).where(ProcessoDisciplina.aluno_id == int(aluno_id), ProcessoDisciplina.status == StatusProcesso.FINALIZADO.value)).all()
        aluno_obj = db.session.get(Aluno, int(aluno_id))
        if not aluno_obj:
            flash("Aluno n\\xc3\\xa3o encontrado.", "danger")
            return redirect(url_for('justica.fada_boletim'))
            
        dt_inicio, dt_limite = JusticaService.get_datas_limites(aluno_obj.turma_id)
        mapa_vinculos = {}

        for p in processos_ativos:
            if JusticaService.verificar_elegibilidade_punicao(p, dt_inicio, dt_limite):
                attr_idx = request.form.get(f'vinculo_infracao_{p.id}')
                if not attr_idx:
                    flash(f"ERRO: A puni\\xc3\\xa7\\xc3\\xa3o (ID {p.id}) deve ser vinculada a um atributo.", "danger")
                    return redirect(url_for('justica.fada_boletim'))
                mapa_vinculos[str(p.id)] = attr_idx

        limites_calculados, erro_limite = JusticaService.calcular_limites_fada(int(aluno_id), mapa_vinculos)
        if erro_limite:
            flash(f"Erro de Valida\\xc3\\xa7\\xc3\\xa3o: {erro_limite}", "danger"); return redirect(url_for('justica.fada_boletim'))

        notas_float = []
        for i, n_str in enumerate(notas):
            try:
                val = float(n_str)
                teto = limites_calculados[i]
                if val > (teto + 0.01):
                    flash(f"ERRO no Atributo {i+1}: Nota {val} excede o limite de {teto:.2f}.", "danger"); return redirect(url_for('justica.fada_boletim'))
                notas_float.append(val)
            except ValueError:
                flash("Nota inv\\xc3\\xa1lida.", "danger"); return redirect(url_for('justica.fada_boletim'))"""

if old_block in text:
    text = text.replace(old_block, new_block)
    with open("backend/controllers/justica_controller.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("Replaced!")
else:
    print("Not found")

