import re
import json
import random
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, session, g, abort
from flask_login import login_required, current_user
from markupsafe import escape

from utils.decorators import coordenador_provas_required
from backend.models.database import db
from backend.models import QuestaoBanco, DelegacaoProva, Disciplina, School, Instrutor, Turma, User, Ciclo
from backend.models.banco_questoes import ConfiguracaoEnvio
from backend.models.disciplina_turma import DisciplinaTurma

questoes_bp = Blueprint('questoes', __name__, url_prefix='/questoes')

# =========================================================================
# ROTAS DO SUPER ADMIN (GESTÃO DO BANCO DE QUESTÕES)
# =========================================================================

@questoes_bp.route('/gerenciar', methods=['GET'])
@login_required
@coordenador_provas_required
def painel_gestao():
    """
    Painel central do Super Admin para gerenciar o Banco de Questões.
    Carrega inicialmente apenas a lista de escolas para o filtro principal.
    """
    escolas = School.query.order_by(School.nome).all()
    return render_template('super_admin/questoes_painel.html', escolas=escolas)


@questoes_bp.route('/api/disciplinas/<int:school_id>', methods=['GET'])
@login_required
@coordenador_provas_required
def api_get_disciplinas(school_id):
    """
    Retorna as disciplinas unificadas (materia) exclusivas da escola selecionada (histórico completo).
    """
    # Retorna TODAS as matérias vinculadas àquela escola, independentemente da edição,
    # garantindo o isolamento dos dados por escola (sem vazar matérias de outras escolas)
    query = db.session.query(Disciplina.materia).join(Turma).filter(Turma.school_id == school_id)
    materias = query.distinct().all()
    lista_materias = [m[0] for m in materias if m[0]]
    return jsonify(sorted(lista_materias))


@questoes_bp.route('/api/edicoes/<int:school_id>', methods=['GET'])
@login_required
@coordenador_provas_required
def api_get_edicoes(school_id):
    """Retorna as edições que pertencem fisicamente à escola selecionada."""
    from backend.models.edicao import Edicao
    edicoes = Edicao.query.filter_by(school_id=school_id).order_by(Edicao.nome).all()
    return jsonify([{"id": e.id, "nome": e.nome} for e in edicoes])

@questoes_bp.route('/api/ciclos/filtro', methods=['GET'])
@login_required
@coordenador_provas_required
def api_get_ciclos_filtro():
    school_id = request.args.get('school_id')
    query = db.session.query(Ciclo.id, Ciclo.nome)
    
    if school_id and school_id != 'all':
        query = query.filter(Ciclo.school_id == int(school_id))
        
    ciclos = query.order_by(Ciclo.nome).distinct().all()
    return jsonify([{'id': c.id, 'nome': c.nome} for c in ciclos])

@questoes_bp.route('/api/materias/filtro', methods=['GET'])
@login_required
@coordenador_provas_required
def api_get_materias_filtro():
    """Retorna as matérias dinamicamente com base na escola, edição e ciclo selecionados."""
    school_id = request.args.get('school_id')
    edicao_id = request.args.get('edicao_id')
    ciclo_id = request.args.get('ciclo_id')
    
    query = db.session.query(Disciplina.materia)
    
    if school_id and school_id != 'all':
        query = query.join(Turma).filter(Turma.school_id == int(school_id))
        if edicao_id and edicao_id != 'all':
            query = query.filter(Turma.edicao_id == int(edicao_id))
            
    if ciclo_id and ciclo_id != 'all':
        query = query.filter(Disciplina.ciclo_id == int(ciclo_id))
            
    materias = query.distinct().all()
    return jsonify(sorted([m[0] for m in materias if m[0]]))

@questoes_bp.route('/api/configuracao', methods=['GET', 'POST'])
@login_required
def api_configuracao_envio():
    """
    GET: Retorna o status atual do toggle (Aberto/Fechado) considerando a Edição.
    POST: Salva ou atualiza o status de abertura do banco.
    """
    school_id = request.args.get('school_id', type=int)
    materia = request.args.get('materia', type=str)
    
    # Lê a edição enviada pelo frontend
    if request.method == 'POST':
        ed_str = request.json.get('edicao')
    else:
        ed_str = request.args.get('edicao')
        
    if ed_str == 'Geral' or not ed_str:
        edicao_id = None
    else:
        try:
            edicao_id = int(ed_str)
        except ValueError:
            edicao_id = None

    if not school_id or not materia:
        return jsonify({'success': False, 'message': 'Escola ou matéria não fornecidas.'}), 400

    try:
        if request.method == 'POST':
            # Trava de Segurança
            papel_usuario = str(getattr(current_user, 'role', '')).lower().strip()
            is_comandante = getattr(current_user, 'is_admin_escola', False)

            if papel_usuario != 'super_admin' and not is_comandante:
                return jsonify({'success': False, 'message': 'Acesso negado.'}), 403

            status = request.json.get('envio_ativo')

            config = ConfiguracaoEnvio.query.filter_by(escola_id=school_id, materia=materia, edicao_id=edicao_id).first()

            if not config:
                config = ConfiguracaoEnvio(escola_id=school_id, materia=materia, edicao_id=edicao_id, envio_ativo=status)
                db.session.add(config)
            else:
                config.envio_ativo = status
                
            db.session.commit()
            
            from backend.services.log_service import LogService
            LogService.log(
                action="Alterou Configuração do Banco de Questões",
                details=f"O recebimento de questões para a matéria '{materia}' foi alterado para: {'ABERTO' if status else 'FECHADO'}."
            )
            
            return jsonify({'success': True})

        # Para chamadas GET (quando a tela carrega)
        config = ConfiguracaoEnvio.query.filter_by(escola_id=school_id, materia=materia, edicao_id=edicao_id).first()
        return jsonify({'envio_ativo': config.envio_ativo if config else False})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Erro no servidor: {str(e)}'}), 500


@questoes_bp.route('/api/instrutores', methods=['GET'])
@login_required
@coordenador_provas_required
def api_get_instrutores():
    """
    Busca apenas os instrutores vinculados àquela matéria específica na escola selecionada.
    """
    school_id = request.args.get('school_id', type=int)
    materia = request.args.get('materia', type=str)

    if not school_id or not materia:
        return jsonify([])

    query = db.session.query(DisciplinaTurma).join(Disciplina).join(Turma).filter(
        Turma.school_id == school_id,
        Disciplina.materia == materia
    )
    vinculos = query.all()

    instrutores_ids = set()
    for v in vinculos:
        if v.instrutor_id_1: instrutores_ids.add(v.instrutor_id_1)
        if v.instrutor_id_2: instrutores_ids.add(v.instrutor_id_2)

    if not instrutores_ids:
        return jsonify([])

    instrutores = Instrutor.query.join(User).filter(Instrutor.id.in_(instrutores_ids)).all()

    resultado = []
    for inst in instrutores:
        nome_exibicao = inst.user.nome_de_guerra or inst.user.nome_completo
        resultado.append({
            'id': inst.id,
            'nome': nome_exibicao
        })

    resultado.sort(key=lambda x: x['nome'])
    return jsonify(resultado)


@questoes_bp.route('/api/delegacoes/listar', methods=['GET'])
@login_required
@coordenador_provas_required
def api_listar_delegacoes():
    """Retorna a lista de instrutores autorizados a gerar provas para a matéria e edição."""
    school_id = request.args.get('school_id', type=int)
    materia = request.args.get('materia', type=str)
    edicao_id = request.args.get('edicao')
    
    if edicao_id == 'Geral':
        edicao_id = None
    elif not edicao_id and g.get('active_edicao'):
        edicao_id = g.active_edicao.id

    query = DelegacaoProva.query.join(Disciplina).filter(
        DelegacaoProva.escola_gestora_id == school_id,
        Disciplina.materia == materia
    )
    if edicao_id:
        query = query.filter(DelegacaoProva.edicao_id == edicao_id)
    else:
        query = query.filter(DelegacaoProva.edicao_id == None)
    delegacoes = query.all()

    return jsonify([{
        'id': d.id,
        'instrutor': d.instrutor.user.nome_de_guerra or d.instrutor.user.nome_completo,
        'data': d.criado_em.strftime('%d/%m/%Y')
    } for d in delegacoes])


@questoes_bp.route('/banco/<int:school_id>/<string:materia>', methods=['GET'])
@login_required
@coordenador_provas_required
def ver_banco_disciplina(school_id, materia):
    """
    Lista as questões de uma matéria/escola para auditoria do Super Admin.
    """
    escola = School.query.get_or_404(school_id)
    questoes = QuestaoBanco.query.join(Disciplina).filter(
        QuestaoBanco.escola_id == school_id,
        Disciplina.materia == materia,
        QuestaoBanco.ativo == True
    ).all()

    base_tmpl = 'base_empty.html' if request.args.get('embed') else 'base.html'
    return render_template(
        'super_admin/questoes_banco_lista.html',
        escola=escola,
        materia=materia,
        questoes=questoes,
        base_template=base_tmpl
    )


@questoes_bp.route('/api/delegar-prova', methods=['POST'])
@login_required
@coordenador_provas_required
def delegar_prova():
    """Processa a autorização de múltiplos instrutores via AJAX sem piscar a tela."""
    dados = request.get_json()
    school_id = dados.get('escola_id')
    materia = dados.get('materia')
    instrutores_ids = dados.get('instrutor_ids', [])

    if not instrutores_ids:
        return jsonify({'success': False, 'message': 'Nenhum instrutor selecionado.'})

    # Agora recebe edicao_id diretamente do form
    edicao_id = dados.get('edicao_id')
    
    if edicao_id == 'Geral':
        edicao_id = None
    elif not edicao_id and g.get('active_edicao'):
        edicao_id = g.active_edicao.id
    
    query = Disciplina.query.join(Turma).filter(
        Turma.school_id == school_id,
        Disciplina.materia == materia
    )
    if edicao_id:
        query = query.filter(Turma.edicao_id == edicao_id)
    disciplina_ref = query.first()

    if not disciplina_ref:
        return jsonify({'success': False, 'message': 'Disciplina não encontrada na edição selecionada para esta escola.'})

    adicionados = 0
    for instrutor_id in instrutores_ids:
        exists = DelegacaoProva.query.filter_by(
            instrutor_id=instrutor_id,
            escola_gestora_id=school_id,
            disciplina_id=disciplina_ref.id,
            edicao_id=edicao_id
        ).first()

        if not exists:
            nova = DelegacaoProva(
                instrutor_id=instrutor_id,
                escola_gestora_id=school_id,
                disciplina_id=disciplina_ref.id,
                edicao_id=edicao_id,
                escolas_fontes=[]
            )
            db.session.add(nova)
            adicionados += 1

    db.session.commit()
    
    if adicionados > 0:
        from backend.services.log_service import LogService
        LogService.log(
            action="Delegou Confecção de Prova",
            details=f"{adicionados} instrutor(es) receberam permissão para gerar a prova da matéria '{materia}'."
        )
        
    return jsonify({'success': True, 'message': f'{adicionados} instrutores autorizados!'})


@questoes_bp.route('/api/delegacao/revogar/<int:id>', methods=['POST'])
@login_required
@coordenador_provas_required
def revogar_delegacao(id):
    """
    Remove a permissão de um instrutor de confeccionar a prova.
    """
    delegacao = DelegacaoProva.query.get_or_404(id)
    
    instrutor_nome = delegacao.instrutor.user.nome_completo
    materia_nome = delegacao.disciplina.materia if delegacao.disciplina else "Desconhecida"
    
    db.session.delete(delegacao)
    db.session.commit()
    
    from backend.services.log_service import LogService
    LogService.log(
        action="Revogou Delegação de Prova",
        details=f"A permissão do instrutor '{instrutor_nome}' para gerar prova de '{materia_nome}' foi revogada."
    )
    
    return jsonify({'success': True})


@questoes_bp.route('/api/questao/remover/<int:id>', methods=['POST'])
@login_required
@coordenador_provas_required
def remover_questao_banco(id):
    """
    Realiza o 'soft delete' de uma questão do banco, desativando-a.
    """
    questao = QuestaoBanco.query.get_or_404(id)
    questao.ativo = False
    db.session.commit()
    
    from backend.services.log_service import LogService
    LogService.log(
        action="Inativou Questão",
        details=f"Questão ID {id} da matéria '{questao.disciplina.materia if questao.disciplina else 'Desconhecida'}' foi inativada."
    )
    
    return jsonify({'success': True, 'message': 'Questão removida com sucesso.'})

@questoes_bp.route('/api/questao/editar/<int:id>', methods=['POST'])
@login_required
@coordenador_provas_required
def editar_questao_banco(id):
    """Edita uma questão do banco."""
    questao = QuestaoBanco.query.get_or_404(id)
    
    dados = request.get_json()
    if not dados:
        return jsonify({'success': False, 'message': 'Nenhum dado recebido.'})

    enunciado = dados.get('enunciado')
    alternativas = dados.get('alternativas')
    resposta_correta = dados.get('resposta_correta')
    assunto = dados.get('assunto')

    if enunciado:
        questao.enunciado = enunciado.strip()
    if alternativas and isinstance(alternativas, dict):
        # Limpar espaços e padronizar chaves para string
        questao.alternativas = {str(k).upper().strip(): str(v).strip() for k, v in alternativas.items()}
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(questao, "alternativas")
    if resposta_correta and isinstance(resposta_correta, str):
        questao.resposta_correta = resposta_correta.upper().strip()
    if assunto is not None:
        questao.assunto = assunto.strip()

    db.session.commit()
    
    from backend.services.log_service import LogService
    LogService.log(
        action="Editou Questão",
        details=f"O administrador editou o enunciado/gabarito da Questão ID {id}."
    )
    
    return jsonify({'success': True, 'message': 'Questão atualizada com sucesso.'})

@questoes_bp.route('/painel-dec', methods=['GET'])
@login_required
@coordenador_provas_required
def painel_dec():
    """Painel do DEC para geração de provas globais e análise unificada."""
        
    escolas = School.query.order_by(School.nome).all()
    materias_db = db.session.query(Disciplina.materia).distinct().all()
    lista_materias = sorted([m[0] for m in materias_db if m[0]])
    return render_template('super_admin/painel_dec_questoes.html', escolas=escolas, materias=lista_materias)


@questoes_bp.route('/dec/gerar-prova', methods=['POST'])
@login_required
@coordenador_provas_required
def gerar_prova_dec():
    """Sorteia as questões globalmente e exibe na tela de impressão imediata."""
    qtd = request.form.get('qtd_questoes', type=int, default=30)
    materia = request.form.get('materia', type=str)
    escola_id = request.form.get('escola_id')
    ciclo_id = request.form.get('ciclo_id')
    edicao_id = request.form.get('edicao_id')
    
    escolas = School.query.order_by(School.nome).all()
    materias_db = db.session.query(Disciplina.materia).distinct().all()
    lista_materias = sorted([m[0] for m in materias_db if m[0]])
    
    if not materia:
        flash("Selecione uma matéria obrigatória.", "danger")
        return render_template('super_admin/painel_dec_questoes.html', escolas=escolas, materias=lista_materias)

    query = QuestaoBanco.query.join(Disciplina).filter(
        QuestaoBanco.ativo == True,
        Disciplina.materia == materia
    )
    
    if escola_id and escola_id != 'all':
        query = query.filter(QuestaoBanco.escola_id == int(escola_id))
        
    if ciclo_id and ciclo_id != 'all':
        query = query.filter(Disciplina.ciclo_id == int(ciclo_id))
        
    if edicao_id and edicao_id not in ['all', 'Geral', '']:
        query = query.join(Turma, Disciplina.turma_id == Turma.id).filter(Turma.edicao_id == int(edicao_id))
        
    todas_questoes = query.all()
    total_disponivel = len(todas_questoes)
    
    if total_disponivel == 0:
        flash("Nenhuma questão foi encontrada no banco para esta disciplina/escola.", "warning")
        return render_template('super_admin/painel_dec_questoes.html', escolas=escolas, materias=lista_materias)
        
    # Adaptação de inteligência: se pediu 30 mas só tem 5, sorteia as 5 sem travar
    qtd_real = min(qtd, total_disponivel)
    
    if qtd_real < qtd:
        flash(f"Atenção: Você solicitou {qtd} questões, mas o banco possui apenas {total_disponivel}. A prova foi gerada com o total disponível.", "info")
        
    questoes_sorteadas = random.sample(todas_questoes, k=qtd_real)
    
    # Compara por ID para garantir precisão
    sorteadas_ids = {q.id for q in questoes_sorteadas}
    questoes_banco = [q for q in todas_questoes if q.id not in sorteadas_ids]
    
    return render_template('super_admin/painel_dec_questoes.html', 
                           escolas=escolas, 
                           materias=lista_materias, 
                           questoes=questoes_sorteadas,
                           questoes_banco=questoes_banco,
                           materia_selecionada=materia,
                           escola_selecionada=escola_id,
                           edicao_selecionada=edicao_id,
                           qtd=qtd)


# =========================================================================
# ROTAS DO INSTRUTOR (ENVIO E MOTOR INTELIGENTE)
# =========================================================================

@questoes_bp.route('/enviar', methods=['GET'])
@login_required
def tela_envio():
    """Exibe as matérias abertas. Filtra para NÃO mostrar a matéria se o instrutor já enviou para AQUELA edição."""
    escola_id = session.get('active_school_id')
    if not escola_id and current_user.user_schools:
        escola_id = current_user.user_schools[0].school_id

    if not escola_id:
        flash("Seu usuário não possui escola ativa selecionada.", "warning")
        return redirect(url_for('main.dashboard'))

    # 1. Busca quais matérias e edições estão abertas nesta escola
    configs_ativas = ConfiguracaoEnvio.query.filter_by(escola_id=escola_id, envio_ativo=True).all()

    # Monta uma lista de dicionários contendo a Matéria e a edição que está aberta
    opcoes_abertas = [{"materia": c.materia, "edicao_id": c.edicao_id, "edicao_nome": c.edicao.nome if c.edicao else 'Geral'} for c in configs_ativas]

    instrutor = Instrutor.query.filter_by(user_id=current_user.id).first()
    
    if not instrutor:
        flash("Você não possui vínculo de instrutor.", "warning")
        return redirect(url_for('main.dashboard'))

    # 1.5. NOVO FILTRO: O instrutor só pode enviar para as disciplinas que ele efetivamente leciona (Vínculo)
    vinculos_db = db.session.query(Disciplina.materia, Turma.edicao_id)\
        .join(DisciplinaTurma, DisciplinaTurma.disciplina_id == Disciplina.id)\
        .join(Turma, Disciplina.turma_id == Turma.id)\
        .filter(
            Turma.school_id == escola_id,
            db.or_(
                DisciplinaTurma.instrutor_id_1 == instrutor.id,
                DisciplinaTurma.instrutor_id_2 == instrutor.id
            )
        ).distinct().all()
        
    materias_vinculadas = set(vinculos_db)

    opcoes_autorizadas = []
    for opcao in opcoes_abertas:
        tem_vinculo = False
        for v_materia, v_edicao in materias_vinculadas:
            if v_materia == opcao["materia"]:
                if opcao["edicao_id"] is None or opcao["edicao_id"] == v_edicao:
                    tem_vinculo = True
                    break
        
        if tem_vinculo:
            opcoes_autorizadas.append(opcao)

    # 3. Retorna apenas as opções (Matéria + Edição) que estão Abertas e Autorizadas
    lista_final_para_dropdown = []
    for opcao in opcoes_autorizadas:
        lista_final_para_dropdown.append(f"{opcao['materia']} | {opcao['edicao_nome']}")

    lista_final_para_dropdown.sort()

    return render_template('instrutor/enviar_questoes.html', materias=lista_final_para_dropdown)

@questoes_bp.route('/minhas-questoes', methods=['GET'])
@login_required
def minhas_questoes_enviadas():
    """Permite ao instrutor visualizar as questões que ele já enviou."""
    escola_id = session.get('active_school_id')
    if not escola_id and current_user.user_schools:
        escola_id = current_user.user_schools[0].school_id

    instrutor = Instrutor.query.filter_by(user_id=current_user.id).first()
    if not instrutor or not escola_id:
        flash("Acesso não autorizado.", "warning")
        return redirect(url_for('main.dashboard'))

    questoes = QuestaoBanco.query.filter_by(
        instrutor_id=instrutor.id,
        escola_id=escola_id
    ).order_by(QuestaoBanco.criado_em.desc()).all()

    return render_template('instrutor/minhas_questoes.html', questoes=questoes)


@questoes_bp.route('/processar', methods=['POST'])
@login_required
def processar_texto():
    dados = request.get_json() or {}
    caixas = dados.get('caixas', [])
    texto_bruto = dados.get('texto_bruto', '')

    if not caixas and not texto_bruto:
        return jsonify({'success': False, 'message': 'Nenhum texto recebido.'})

    questoes_processadas = []

    # 1. Se recebemos as caixas individualmente (uma para cada textarea preenchida na tela)
    if caixas and isinstance(caixas, list):
        for c in caixas:
            txt = str(c).strip()
            if txt:
                extraidas = extrair_e_limpar_questoes(txt)
                questoes_processadas.extend(extraidas)
    # 2. Fallback para envio unificado em texto_bruto
    elif texto_bruto:
        questoes_processadas = extrair_e_limpar_questoes(texto_bruto)

    if not questoes_processadas:
        return jsonify({'success': False, 'message': 'Padrão de questões não identificado. Verifique se as alternativas (A, B, C, D) e o gabarito foram informados.'})

    return jsonify({'success': True, 'total': len(questoes_processadas), 'questoes': questoes_processadas})


@questoes_bp.route('/salvar', methods=['POST'])
@login_required
def salvar_questoes():
    try:
        dados = request.get_json()
        materia_full = dados.get('materia', '')
        # Remove a parte da edicao (ex: "Materia | Edicao 1")
        materia = materia_full.split(' | ')[0].strip() if ' | ' in materia_full else materia_full.strip()
        
        questoes_lista = dados.get('questoes', [])

        escola_id = session.get('active_school_id') or (current_user.user_schools[0].school_id if current_user.user_schools else None)
        instrutor = Instrutor.query.filter_by(user_id=current_user.id).first()

        papel_usuario = str(getattr(current_user, 'role', '')).lower().strip()
        if not instrutor and papel_usuario == 'super_admin':
            instrutor = Instrutor.query.first() # Fallback para testes do admin

        disciplina = Disciplina.query.join(Turma).filter(
            Turma.school_id == escola_id,
            Disciplina.materia == materia
        ).first() if escola_id else None
        if not disciplina:
            disciplina = Disciplina.query.filter_by(materia=materia).first()

        if not disciplina:
            return jsonify({'success': False, 'message': 'Disciplina não encontrada.'}), 404

        # === NOVA REGRA 2: Filtro Anti-Duplicidade ===
        # Puxa apenas os textos (enunciados) que já existem no banco para esta matéria
        existentes = QuestaoBanco.query.filter_by(disciplina_id=disciplina.id).with_entities(QuestaoBanco.enunciado).all()
        enunciados_db = {q[0].strip().lower() for q in existentes}

        salvas_count = 0
        duplicadas_count = 0

        for q_data in questoes_lista:
            enunciado_limpo = q_data['enunciado'].strip()

            # Se o texto já existe no banco, pula essa questão
            if enunciado_limpo.lower() in enunciados_db:
                duplicadas_count += 1
                continue

            # Adiciona na lista temporária para evitar que o instrutor cole a mesma questão 2x no mesmo envio
            enunciados_db.add(enunciado_limpo.lower())

            nova_questao = QuestaoBanco(
                disciplina_id=disciplina.id,
                escola_id=escola_id,
                instrutor_id=instrutor.id,
                enunciado=enunciado_limpo,
                alternativas=q_data['alternativas'],
                resposta_correta=q_data['resposta_correta'],
                assunto="Geral",
                ativo=True
            )
            db.session.add(nova_questao)
            salvas_count += 1

        db.session.commit()
        
        if salvas_count > 0:
            from backend.services.log_service import LogService
            LogService.log(
                action="Enviou Questões",
                details=f"O usuário enviou {salvas_count} nova(s) questão(ões) para o banco da matéria '{materia}'."
            )

        # Monta a mensagem inteligente que aparecerá na tela final do seu colega
        msg_final = f'{salvas_count} questões inéditas salvas com sucesso no banco!'
        if duplicadas_count > 0:
            msg_final += f' (Atenção: {duplicadas_count} questões foram ignoradas por já existirem no banco).'

        return jsonify({'success': True, 'message': msg_final})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


def extrair_e_limpar_questoes(texto):
    if not texto or not str(texto).strip():
        return []

    # 1. NORMALIZAÇÃO E LIMPEZA (Word, PDF, caracteres invisíveis e segurança contra tags HTML)
    texto_limpo = re.sub(r'[\u200B-\u200D\uFEFF\u2060]', '', str(texto))
    texto_limpo = texto_limpo.replace('\r\n', '\n').replace('\r', '\n')
    texto_limpo = re.sub(r'[\u00A0\u202F\u2007\t]', ' ', texto_limpo)
    texto_limpo = re.sub(r'<\s*script[^>]*>.*?<\s*/\s*script\s*>', '', texto_limpo, flags=re.IGNORECASE | re.DOTALL)
    texto_limpo = re.sub(r'<[^>]+>', '', texto_limpo)

    SEP = r'[ \t]*[\.\-\–\—\―\)\]\:]'

    # Regex para gabarito explícito em final de linha ou entre parênteses/colchetes
    # Suporta: Gabarito: C | Resp: C | Resp.: C | Gab: C | Resposta correta: Letra C | Alternativa correta: (C) | Correta - C
    PADRAO_GABARITO = re.compile(
        r'(?:^|\n|[ \t]+|[(\[])'
        r'(?:'
            r'gabarito(?:[ \t]+oficial)?|'
            r'gab\.?|'
            r'resp\.?(?:[ \t]+correta|[ \t]+certa)?|'
            r'resposta(?:[ \t]+correta|[ \t]+certa|[ \t]+oficial)?|'
            r'(?:alternativa|op[çc][aã]o)[ \t]+(?:correta|certa)|'
            r'correta|'
            r'certa'
        r')'
        r'[ \t]*(?:[\:\-\–\—\=][ \t]*|[ \t]+)'
        r'(?:(?:a[ \t]+)?(?:letra|alternativa|op[çc][aã]o|item)[ \t]+)?'
        r'[\(\[]?[ \t]*([A-Ea-e])[ \t]*[\)\]\.]?[ \t]*[\)\]]?'
        r'(?=[ \t]*(?:\n|$))',
        re.IGNORECASE
    )

    PADRAO_GABARITO_PARENTESES = re.compile(
        r'[\(\[]\s*(?:gabarito|gab\.?|resp\.?|resposta(?:\s+correta|\s+certa)?|correta|certa)'
        r'\s*[\:\-\–\—\=]?\s*(?:letra\s+)?([A-Ea-e])\s*[\.]?\s*[\)\]]',
        re.IGNORECASE
    )

    PADRAO_LINHA_SO_GABARITO = re.compile(
        r'^\s*[\(\[]?\s*(?:'
            r'gabarito(?:\s+oficial)?|'
            r'gab\.?|'
            r'resp\.?(?:\s+correta|\s+certa)?|'
            r'resposta(?:\s+correta|\s+certa|\s+oficial)?|'
            r'(?:alternativa|op[çc][aã]o)\s+(?:correta|certa)|'
            r'correta|'
            r'certa'
        r')'
        r'\s*(?:[\:\-\–\—\=]\s*|\s+)'
        r'(?:(?:a\s+)?(?:letra|alternativa|op[çc][aã]o|item)\s+)?'
        r'[\(\[]?\s*([A-Ea-e])\s*[\)\]\.]?\s*[\)\]]?\s*$',
        re.IGNORECASE
    )

    def _tem_estrutura_questao(bloco_txt):
        """Verifica se um bloco já contém ao menos as alternativas A, B, C e D em sequência."""
        encontrados = 0
        pos = 0
        for letra in ['A', 'B', 'C', 'D']:
            m = re.search(rf'(?:^|\n)\s*[•●▪\*\-]?\s*[\(\[]?{letra}{SEP}\s*\S', bloco_txt[pos:], re.IGNORECASE)
            if not m:
                m = re.search(rf'(?:^|\s)[•●▪\*\-]?\s*[\(\[]?{letra}{SEP}\s+\S', bloco_txt[pos:], re.IGNORECASE)
            if m:
                encontrados += 1
                pos += m.end()
            else:
                break
        return encontrados >= 4

    padrao_inicio_questao = re.compile(
        r'^\s*(?:'
            r'[\(\[]?(?:quest[aã]o|q\.?|pergunta)\s*(?:n[º°\.]?\s*)?0?\d{1,4}\s*(?:[\.\-\–\—\―\)\]\:]|\º[\.\)\-\s]?|\ª[\.\)\-\s]?)?\s*(?=\S|$)|'
            r'0?\d{1,4}\s*(?:[\.\-\–\—\―\)\]\:]|\º[\.\)\-\s]|\ª[\.\)\-\s])\s*(?=\S|$)'
        r')',
        re.IGNORECASE
    )

    padrao_alt_A = re.compile(rf'^\s*[•●▪\*\-]?[ \t]*[\(\[]?[Aa]{SEP}\s*\S')

    # 2. FATIAMENTO EM BLOCOS (Respeita caixas separadas, quebras manuais e numerações)
    secoes_manuais = re.split(r'\n*===NOVA_QUESTAO===\n*', texto_limpo)
    blocos = []

    for secao in secoes_manuais:
        if not secao.strip():
            continue
        linhas = secao.split('\n')
        bloco_atual = []

        for linha in linhas:
            eh_inicio = bool(padrao_inicio_questao.match(linha))
            eh_alt_A = bool(padrao_alt_A.match(linha))

            if eh_inicio and bloco_atual:
                texto_acumulado = '\n'.join(bloco_atual)
                # Só inicia nova questão se o bloco anterior já tiver completado as alternativas A-D
                if _tem_estrutura_questao(texto_acumulado):
                    blocos.append(texto_acumulado.strip())
                    linha_sem_num = padrao_inicio_questao.sub('', linha, count=1).strip()
                    bloco_atual = [linha_sem_num] if linha_sem_num else []
                    continue
            elif eh_inicio and not bloco_atual:
                linha = padrao_inicio_questao.sub('', linha, count=1).strip()
                if not linha:
                    continue

            # Se o bloco atual já contém alternativas A-D e encontramos um novo 'A)',
            # significa que uma nova questão começou mesmo sem ter número no enunciado
            if eh_alt_A and bloco_atual:
                texto_acumulado = '\n'.join(bloco_atual)
                if _tem_estrutura_questao(texto_acumulado):
                    split_idx = -1
                    for i in range(len(bloco_atual) - 1, -1, -1):
                        if not bloco_atual[i].strip():
                            split_idx = i
                            break
                    if split_idx != -1:
                        parte_antiga = '\n'.join(bloco_atual[:split_idx]).strip()
                        parte_nova = bloco_atual[split_idx + 1:]
                        if _tem_estrutura_questao(parte_antiga):
                            blocos.append(parte_antiga)
                            bloco_atual = parte_nova + [linha]
                            continue
                    else:
                        blocos.append(texto_acumulado.strip())
                        bloco_atual = [linha]
                        continue

            bloco_atual.append(linha)

            # Se a linha atual é um gabarito isolado (ou alternativa E com gabarito na mesma linha)
            # e o bloco já possui estrutura de alternativas A-D, encerra a questão atual
            if PADRAO_LINHA_SO_GABARITO.match(linha) or (
                re.match(r'^\s*[•●▪\*\-]?\s*[\(\[]?[Ee]' + SEP, linha) and PADRAO_GABARITO.search(linha)
            ):
                texto_acumulado = '\n'.join(bloco_atual)
                if _tem_estrutura_questao(texto_acumulado):
                    blocos.append(texto_acumulado.strip())
                    bloco_atual = []

        if bloco_atual:
            texto_restante = '\n'.join(bloco_atual).strip()
            if texto_restante:
                blocos.append(texto_restante)

    def _localizar_alternativas(texto_bloco):
        """
        Localiza as posições exatas das alternativas A, B, C, D e (opcionalmente) E em ordem estrita.
        Prioriza marcadores no início de linha para nunca cortar palavras terminadas em a., b., c., d., e.
        (como 'Alt + Tab.', 'Ctrl + C.', 'Win + E.', 'Android.', 'polícia.').
        """
        # Estratégia 1: Marcadores no início de linha
        padrao_linha_A = re.compile(rf'(?:^|\n)[ \t]*([•●▪\*\-]?\s*[\(\[]?[Aa]{SEP}[ \t]*)')
        candidatos_A = list(padrao_linha_A.finditer(texto_bloco))

        for cand_a in reversed(candidatos_A):
            matches = {'A': cand_a}
            pos_busca = cand_a.end()
            valido = True
            for letra in ['B', 'C', 'D']:
                pat = re.compile(rf'\n[ \t]*([•●▪\*\-]?\s*[\(\[]?[{letra}{letra.lower()}]{SEP}[ \t]*)')
                m = pat.search(texto_bloco, pos_busca)
                if m:
                    matches[letra] = m
                    pos_busca = m.end()
                else:
                    valido = False
                    break
            if valido:
                pat_e = re.compile(rf'\n[ \t]*([•●▪\*\-]?\s*[\(\[]?[Ee]{SEP}[ \t]*)')
                m_e = pat_e.search(texto_bloco, pos_busca)
                if m_e:
                    matches['E'] = m_e
                return matches

        # Estratégia 2: Alternativas inline (na mesma linha) ou mistas
        padrao_inline_A = re.compile(rf'(?:^|\s)([•●▪\*\-]?\s*[\(\[]?[Aa]{SEP}\s+)')
        candidatos_inline_A = list(padrao_inline_A.finditer(texto_bloco))

        for cand_a in reversed(candidatos_inline_A):
            matches = {'A': cand_a}
            pos_busca = cand_a.end()
            valido = True
            for letra in ['B', 'C', 'D']:
                pat = re.compile(rf'(?:\n|\s{{2,}}|[.;]\s+)([•●▪\*\-]?\s*[\(\[]?[{letra}{letra.lower()}]{SEP}\s+)')
                m = pat.search(texto_bloco, pos_busca)
                if not m:
                    pat = re.compile(rf'\s+([•●▪\*\-]?\s*[\(\[]?[{letra}{letra.lower()}][ \t]*[\)\]\-\–\—]\s+)')
                    m = pat.search(texto_bloco, pos_busca)
                if m:
                    matches[letra] = m
                    pos_busca = m.end()
                else:
                    valido = False
                    break
            if valido:
                pat_e = re.compile(rf'(?:\n|\s{{2,}}|[.;]\s+|\s+)([•●▪\*\-]?\s*[\(\[]?[Ee]{SEP}\s+)')
                m_e = pat_e.search(texto_bloco, pos_busca)
                if m_e:
                    matches['E'] = m_e
                return matches

        return None

    questoes = []
    for bloco in blocos:
        if not bloco:
            continue
        avisos = []
        letra_correta = None
        bloco_trabalho = bloco

        # 1. Identifica e extrai o gabarito sem apagar nada após ele
        gab_matches = list(PADRAO_GABARITO.finditer(bloco_trabalho))
        if gab_matches:
            ultimo_gab = gab_matches[-1]
            letra_correta = ultimo_gab.group(1).upper()
            inicio_g, fim_g = ultimo_gab.span()
            prefixo = '\n' if bloco_trabalho[inicio_g:fim_g].startswith('\n') else ''
            bloco_trabalho = (bloco_trabalho[:inicio_g] + prefixo + bloco_trabalho[fim_g:]).strip()
        else:
            gab_par = list(PADRAO_GABARITO_PARENTESES.finditer(bloco_trabalho))
            if gab_par:
                ultimo_gab = gab_par[-1]
                letra_correta = ultimo_gab.group(1).upper()
                inicio_g, fim_g = ultimo_gab.span()
                bloco_trabalho = (bloco_trabalho[:inicio_g] + ' ' + bloco_trabalho[fim_g:]).strip()

        # 2. Localiza as alternativas A, B, C, D, (E) em ordem
        alt_matches = _localizar_alternativas(bloco_trabalho)
        if not alt_matches:
            continue

        ordem_letras = [l for l in ['A', 'B', 'C', 'D', 'E'] if l in alt_matches]
        enunciado = bloco_trabalho[:alt_matches['A'].start()].strip()
        enunciado = padrao_inicio_questao.sub('', enunciado, count=1).strip()

        alternativas = {'A': '', 'B': '', 'C': '', 'D': '', 'E': ''}
        for i, letra in enumerate(ordem_letras):
            inicio_texto = alt_matches[letra].end()
            marcador_bruto = alt_matches[letra].group(1)
            if '*' in marcador_bruto and not letra_correta:
                letra_correta = letra

            if i + 1 < len(ordem_letras):
                prox_letra = ordem_letras[i + 1]
                fim_texto = alt_matches[prox_letra].start()
            else:
                fim_texto = len(bloco_trabalho)

            texto_alt = bloco_trabalho[inicio_texto:fim_texto].strip()

            # Verifica marcação de resposta correta no final da alternativa, ex: (Correta) ou [X]
            m_marca = re.search(r'\s*(?:[\(\[]\s*(?:correta|certa|x)\s*[\)\]]|\*+)\s*$', texto_alt, re.IGNORECASE)
            if m_marca:
                if not letra_correta:
                    letra_correta = letra
                texto_alt = texto_alt[:m_marca.start()].strip()

            texto_alt = re.sub(r'\s*\n\s*', ' ', texto_alt).strip()
            alternativas[letra] = texto_alt

        if 'E' not in alt_matches or not alternativas['E']:
            avisos.append('Alternativa E não identificada no texto. Verifique se a questão possui 4 ou 5 alternativas.')

        if not letra_correta:
            letra_correta = 'A'
            avisos.append('Gabarito não identificado automaticamente no texto. Selecione a alternativa correta abaixo.')

        if enunciado.isupper() and len(enunciado) > 10:
            enunciado = enunciado.capitalize()

        if enunciado and any(alternativas.values()):
            questoes.append({
                'enunciado': enunciado,
                'alternativas': alternativas,
                'resposta_correta': letra_correta,
                'avisos': avisos
            })

    return questoes


    # =========================================================================

@questoes_bp.route('/minhas-provas', methods=['GET'])
@login_required
def minhas_provas():
    """Tela onde o instrutor vê as delegações que recebeu para montar provas."""

    # 1. Verifica se o usuário logado é realmente um instrutor
    instrutor = Instrutor.query.filter_by(user_id=current_user.id).first()

    if not instrutor:
        flash("Você não possui um perfil de instrutor ativo.", "warning")
        return redirect(url_for('main.dashboard'))

    # 2. Busca no banco todas as matérias que ele foi autorizado a gerar prova
    delegacoes = DelegacaoProva.query.filter_by(instrutor_id=instrutor.id).all()

    return render_template('instrutor/minhas_provas.html', delegacoes=delegacoes)

@questoes_bp.route('/gerar-rascunho/<int:delegacao_id>', methods=['POST'])
@login_required
def gerar_rascunho(delegacao_id):
    """Realiza o sorteio aleatório das questões e cria/atualiza o Rascunho."""
    qtd = request.form.get('qtd_questoes', type=int, default=30)
    delegacao = DelegacaoProva.query.get_or_404(delegacao_id)

    # 1. Trava de Segurança (IDOR): Garante que o usuário logado é o dono desta delegação
    instrutor = Instrutor.query.filter_by(user_id=current_user.id).first()
    if not instrutor or delegacao.instrutor_id != instrutor.id:
        flash("Acesso negado. Esta delegação pertence a outro instrutor.", "danger")
        return redirect(url_for('questoes.minhas_provas'))

    # 2. Busca TODAS as questões ATIVAS desta disciplina no banco
    todas_questoes = QuestaoBanco.query.filter_by(
        disciplina_id=delegacao.disciplina_id,
        ativo=True
    ).all()

    # 3. Valida se há questões suficientes para o sorteio
    if len(todas_questoes) < qtd:
        flash(f"Erro: O banco possui apenas {len(todas_questoes)} questões cadastradas para esta matéria. Peça aos instrutores para enviarem mais ou diminua a quantidade da prova.", "warning")
        return redirect(url_for('questoes.minhas_provas'))

    # 4. A Mágica do Sorteio Aleatório
    questoes_sorteadas = random.sample(todas_questoes, k=qtd)
    ids_sorteados = [q.id for q in questoes_sorteadas] # Salva apenas os IDs numéricos (ocupa menos espaço no banco)

    # 5. Salva no banco de dados (Cria novo rascunho ou atualiza se já existir)
    rascunho = RascunhoProva.query.filter_by(delegacao_id=delegacao.id).first()
    if rascunho:
        rascunho.questoes_selecionadas = ids_sorteados
    else:
        rascunho = RascunhoProva(delegacao_id=delegacao.id, questoes_selecionadas=ids_sorteados)
        db.session.add(rascunho)

    db.session.commit()

    flash("Rascunho gerado com sucesso! Você já pode conferir a prova.", "success")
    # Redirecionará para a tela do rascunho (que criaremos no próximo passo)
    return redirect(url_for('questoes.ver_rascunho', delegacao_id=delegacao.id))

@questoes_bp.route('/rascunho/<int:delegacao_id>', methods=['GET'])
@login_required
def ver_rascunho(delegacao_id):
    """Exibe o rascunho interativo da prova com as questões sorteadas."""
    delegacao = DelegacaoProva.query.get_or_404(delegacao_id)

    # Trava de Segurança
    instrutor = Instrutor.query.filter_by(user_id=current_user.id).first()
    if not instrutor or delegacao.instrutor_id != instrutor.id:
        flash("Acesso negado.", "danger")
        return redirect(url_for('questoes.minhas_provas'))

    rascunho = RascunhoProva.query.filter_by(delegacao_id=delegacao.id).first()

    if not rascunho or not rascunho.questoes_selecionadas:
        flash("Nenhum rascunho gerado ainda. Sorteie as questões primeiro.", "info")
        return redirect(url_for('questoes.minhas_provas'))

    # Carrega as questões reais do banco baseadas na lista de IDs sorteados
    questoes = []
    for qid in rascunho.questoes_selecionadas:
        q = QuestaoBanco.query.get(qid)
        if q and q.ativo:
            questoes.append(q)

    return render_template('instrutor/rascunho_prova.html', delegacao=delegacao, questoes=questoes)
