import re
import json
import random
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, session, g
from flask_login import login_required, current_user
from markupsafe import escape

from utils.decorators import super_admin_required
from backend.models.database import db
from backend.models import QuestaoBanco, DelegacaoProva, Disciplina, School, Instrutor, Turma, User
from backend.models.banco_questoes import ConfiguracaoEnvio
from backend.models.disciplina_turma import DisciplinaTurma

questoes_bp = Blueprint('questoes', __name__, url_prefix='/questoes')

# =========================================================================
# ROTAS DO SUPER ADMIN (GESTÃO DO BANCO DE QUESTÕES)
# =========================================================================

@questoes_bp.route('/gerenciar', methods=['GET'])
@login_required
@super_admin_required
def painel_gestao():
    """
    Painel central do Super Admin para gerenciar o Banco de Questões.
    Carrega inicialmente apenas a lista de escolas para o filtro principal.
    """
    escolas = School.query.order_by(School.nome).all()
    return render_template('super_admin/questoes_painel.html', escolas=escolas)


@questoes_bp.route('/api/disciplinas/<int:school_id>', methods=['GET'])
@login_required
@super_admin_required
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
@super_admin_required
def api_get_edicoes(school_id):
    """Retorna as edições que pertencem fisicamente à escola selecionada."""
    from backend.models.edicao import Edicao
    edicoes = Edicao.query.filter_by(school_id=school_id).order_by(Edicao.nome).all()
    return jsonify([{"id": e.id, "nome": e.nome} for e in edicoes])

@questoes_bp.route('/api/materias/filtro', methods=['GET'])
@login_required
@super_admin_required
def api_get_materias_filtro():
    """Retorna as matérias dinamicamente com base na escola e edição selecionadas."""
    school_id = request.args.get('school_id')
    edicao_id = request.args.get('edicao_id')
    
    query = db.session.query(Disciplina.materia)
    
    if school_id and school_id != 'all':
        query = query.join(Turma).filter(Turma.school_id == int(school_id))
        if edicao_id and edicao_id != 'all':
            query = query.filter(Turma.edicao_id == int(edicao_id))
            
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
            return jsonify({'success': True})

        # Para chamadas GET (quando a tela carrega)
        config = ConfiguracaoEnvio.query.filter_by(escola_id=school_id, materia=materia, edicao_id=edicao_id).first()
        return jsonify({'envio_ativo': config.envio_ativo if config else False})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Erro no servidor: {str(e)}'}), 500


@questoes_bp.route('/api/instrutores', methods=['GET'])
@login_required
@super_admin_required
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
@super_admin_required
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
@super_admin_required
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

    return render_template(
        'super_admin/questoes_banco_lista.html',
        escola=escola,
        materia=materia,
        questoes=questoes
    )


@questoes_bp.route('/api/delegar-prova', methods=['POST'])
@login_required
@super_admin_required
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
    return jsonify({'success': True, 'message': f'{adicionados} instrutores autorizados!'})


@questoes_bp.route('/api/delegacao/revogar/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def revogar_delegacao(id):
    """
    Remove a permissão de um instrutor de confeccionar a prova.
    """
    delegacao = DelegacaoProva.query.get_or_404(id)
    db.session.delete(delegacao)
    db.session.commit()
    return jsonify({'success': True})


@questoes_bp.route('/api/questao/remover/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def remover_questao_banco(id):
    """
    Realiza o 'soft delete' de uma questão do banco, desativando-a.
    """
    questao = QuestaoBanco.query.get_or_404(id)
    questao.ativo = False
    db.session.commit()
    return jsonify({'success': True, 'message': 'Questão removida com sucesso.'})


@questoes_bp.route('/painel-dec', methods=['GET'])
@login_required
@super_admin_required
def painel_dec():
    """Painel do DEC para geração de provas globais e análise unificada."""
    escolas = School.query.order_by(School.nome).all()
    materias_db = db.session.query(Disciplina.materia).distinct().all()
    lista_materias = sorted([m[0] for m in materias_db if m[0]])
    return render_template('super_admin/painel_dec_questoes.html', escolas=escolas, materias=lista_materias)


@questoes_bp.route('/dec/gerar-prova', methods=['POST'])
@login_required
@super_admin_required
def gerar_prova_dec():
    """Sorteia as questões globalmente e exibe na tela de impressão imediata."""
    qtd = request.form.get('qtd_questoes', type=int, default=30)
    materia = request.form.get('materia', type=str)
    escola_id = request.form.get('escola_id')
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
    
    return render_template('super_admin/painel_dec_questoes.html', 
                           escolas=escolas, 
                           materias=lista_materias, 
                           questoes=questoes_sorteadas, 
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
    dados = request.get_json()
    texto_bruto = dados.get('texto_bruto', '')

    if not texto_bruto:
        return jsonify({'success': False, 'message': 'Nenhum texto recebido.'})

    questoes_processadas = extrair_e_limpar_questoes(texto_bruto)

    if not questoes_processadas:
        return jsonify({'success': False, 'message': 'Padrão de questões não identificado.'})

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

        # Monta a mensagem inteligente que aparecerá na tela final do seu colega
        msg_final = f'{salvas_count} questões inéditas salvas com sucesso no banco!'
        if duplicadas_count > 0:
            msg_final += f' (Atenção: {duplicadas_count} questões foram ignoradas por já existirem no banco).'

        return jsonify({'success': True, 'message': msg_final})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


def extrair_e_limpar_questoes(texto):
    questoes = []

    # 1. BLINDAGEM DE SEGURANÇA (Evita injeção de scripts e limpa Word)
    texto_seguro = str(escape(texto))
    texto_seguro = re.sub(r'[\u200B-\u200D\uFEFF]', '', texto_seguro)

    # 2. PROCESSAMENTO
    blocos = re.split(r'\n\s*\d+[\.\-\)]\s*', '\n' + texto_seguro)
    blocos = [b.strip() for b in blocos if b.strip()]

    for bloco in blocos:
        gabarito_match = re.search(r'(?:gabarito|resposta|correta)[\s\:\-]+([A-Ea-e])', bloco, re.IGNORECASE)
        if gabarito_match:
            letra_correta = gabarito_match.group(1).upper()
            bloco_sem_gabarito = re.sub(r'(?:gabarito|resposta|correta)[\s\:\-]+[A-Ea-e].*', '', bloco, flags=re.IGNORECASE | re.DOTALL).strip()

            padrao_alt = r'\n?\s*[A-Ea-e][\.\-\)]\s*'
            partes = re.split(padrao_alt, bloco_sem_gabarito)

            if len(partes) >= 6:
                enunciado = partes[0].strip()
                alt_a, alt_b, alt_c, alt_d, alt_e = [p.strip() for p in partes[1:6]]

                if enunciado.isupper(): enunciado = enunciado.capitalize()

                questoes.append({
                    'enunciado': enunciado,
                    'alternativas': { 'A': alt_a, 'B': alt_b, 'C': alt_c, 'D': alt_d, 'E': alt_e },
                    'resposta_correta': letra_correta,
                    'avisos': []
                })
    return questoes

    # =========================================================================
    # ROTAS DO INSTRUTOR RESPONSÁVEL (GERAÇÃO DE PROVAS - MÓDULO 3)
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