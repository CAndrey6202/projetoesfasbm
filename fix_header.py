import re

file = 'templates/questionario/responder_avaliacao_instrutores.html'
with open(file, 'r', encoding='utf-8') as f:
    text = f.read()

header_html = '''<div class="mb-5">
    <div class="card border shadow-sm">
        <div class="card-body p-4">
            <h5 class="fw-bold mb-3">TÍTULO: Avaliação de Curso - {{ aluno.turma.edicao.nome if aluno.turma.edicao else 'Edição Padrão' }} - {{ campanha.titulo }} - {{ aluno.turma.school.name }}</h5>
            
            <p class="mb-3" style="text-align: justify;"><strong>DESCRIÇÃO:</strong> O Departamento de Educação e Cultura da Brigada Militar tendo como uma das suas competências "promover pesquisa e estudo com vistas ao aprimoramento do ensino e do aprendizado", nos termos do art. 5º, inc. XIV, de seu Regimento Interno, vem através deste questionário, coletar as percepções dos discentes do <strong>{{ aluno.turma.edicao.nome if aluno.turma.edicao else 'Curso' }}</strong> em relação à grade curricular, ementas, instrutores e organização geral das disciplinas e do curso. Para tanto, solicito vossos préstimos no sentido de responder ao presente questionário logo após a conclusão da disciplina, bem como a realização das provas. Tais informações subsidiarão estudo conduzido pela Divisão de Ensino e Treinamento do Departamento de Educação e Cultura, a quem compete a atualização curricular e a análise das metodologias de ensino.</p>
            
            <p class="mb-0"><strong>Escala:</strong><br>
            5 = Muito Satisfeito | 4 = Satisfeito | 3 = Neutro | 2 = Insatisfeito | 1 = Muito Insatisfeito</p>
            
            <hr class="my-4">
            <div class="alert alert-info mb-0 d-flex align-items-center">
                <i class="fas fa-user-secret fa-2x me-3"></i>
                <div>
                    <strong>Sua avaliação é 100% anônima e confidencial.</strong><br>
                    O sistema utiliza tokens criptográficos descartáveis. Nenhuma informação pessoal ou vínculo com sua matrícula é salvo junto com as suas notas.
                </div>
            </div>
        </div>
    </div>
</div>'''

text = re.sub(
    r'<div class="text-center mb-5">\s*<h2 class="fw-bold" style="color: #2c3e50;">Avaliação de Módulo e Instrutores</h2>\s*<p class="text-muted">Por favor, responda o questionário abaixo\.<br>\s*<strong>Sua avaliação é 100% anônima e confidencial\.</strong></p>\s*</div>',
    header_html,
    text
)

with open(file, 'w', encoding='utf-8') as f:
    f.write(text)
print('Header Replaced')
