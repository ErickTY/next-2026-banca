# NEXT 2026 — Sistema de Avaliação da Banca

Aplicação web responsiva para o Challenge DATEN | Microsoft Smart AI Vision (24/10/2026). Backend Flask no Vercel, dados no Supabase por HTTPS/Data API. Não há conexão PostgreSQL direta nem variável DATABASE_URL.

## Configuração inicial (obrigatória)

1. No painel do Supabase, abra o projeto dedicado à banca (referência **iwfqmdsrourtdvrgiums**).
2. Vá em SQL Editor → New Query, cole TODO o conteúdo de [supabase/schema.sql](supabase/schema.sql) e pressione Run. Isso cria cinco tabelas, as nove equipes, e duas funções RPC transacionais.
3. Vá em Project Settings → API Keys e copie uma **Secret key** (sb_secret_) para uso exclusivo no servidor. Uma chave legada **service_role** também funciona. NUNCA use uma chave publishable/anon para o servidor nem publique a chave no GitHub.
4. Em Vercel → next-2026-banca → Settings → Environment Variables, defina no ambiente Production:

| Variável | Valor |
|---|---|
| SUPABASE_URL | https://iwfqmdsrourtdvrgiums.supabase.co |
| SUPABASE_SECRET_KEY | chave privada do projeto Supabase |
| SECRET_KEY | segredo aleatório com no mínimo 32 caracteres |
| ADMIN_USERNAME | coordenacao |
| ADMIN_PASSWORD | senha forte com no mínimo 12 caracteres |

Se utilizar a chave legada service_role, use SUPABASE_SERVICE_ROLE_KEY em vez de SUPABASE_SECRET_KEY.
5. No Vercel, faça Deployments → Redeploy para incorporar as variáveis.
6. Verifique [health](https://next-2026-banca.vercel.app/health). A resposta esperada é JSON contendo ok=true e backend=supabase-rest.
7. Acesse a página /login com coordenacao e sua senha. A conta administrativa é criada automaticamente no primeiro login. Cadastre os avaliadores e repasse suas senhas por canal privado.

**Atenção:** A chave secreta Supabase só deve existir no ambiente protegido do Vercel. Não deve aparecer em GitHub, HTML, JavaScript ou mensagens. Os esquemas são instalados pelo SQL Editor uma vez; a aplicação usa só chamadas HTTPS à API do Supabase.

## Funcionalidades

- Nove grupos e estandes A22–A27 / A37–A39.
- Identificação dos participantes A1–A3 e D1–D2.
- Três critérios de 0 a 5, total 15 por avaliador.
- Cronômetro de cinco minutos compartilhado e controlado pela coordenação.
- Reinício e minuto extra somente com justificativa, registrado em auditoria.
- Avaliações individuais por usuário; persistência e pontuação no Supabase.
- Cadastro de avaliadores, alteração de nomes, bloqueio de grupos e CSV.

Os resultados são provisórios da arena, sem conversão automática em classificação final. O nome do Grupo 1 é Datacore; o Grupo 6 ainda exige confirmação do nome.

## Painel de classificação ao vivo e cronômetro (12/10/2026)

- O **administrador** vê uma prévia do ranking no painel principal e a classificação completa em **/admin/results**.
- O ranking mostra posição, média C1, média C2, média C3, média total de **0 a 15** e fichas recebidas / avaliadores ativos.
- A página consulta **/api/results** a cada **3 segundos** enquanto estiver aberta, sem recarregamento.
- A ordenação é pela **média das avaliações** (não soma). Empates recebem a mesma posição; grupos sem notas não são classificados.
- Grupos com fichas ainda não recebidas aparecem como **Parcial**. O ranking é visível apenas para a coordenação.
- O botão **Resetar 05:00** aparece só para o administrador, exige confirmação e verifica autorização no servidor e no Supabase.
- Os avaliadores apenas visualizam o cronômetro: não podem iniciar, pausar, encerrar ou reiniciar.
- Reiniciar o tempo não apaga notas ou usuários; a operação deixa registro de auditoria.

### Migração GAVS-5 → Datacore no projeto Supabase já instalado

Execute **somente** o SQL de [supabase/migrations/20261012_renomear_datacore.sql](supabase/migrations/20261012_renomear_datacore.sql) em Supabase → SQL Editor.
Essa mudança é segura e idempotente; preserva todas as notas, os cronômetros e os usuários.
O novo [schema.sql](supabase/schema.sql) já cria o Grupo 1 como **Datacore** em futuras instalações.
**Não execute novamente o script de criação de usuários e senhas para esta atualização.**

## Contingência por fotografia e limpeza de notas

O painel da coordenação está disponível em **/admin/contingencia** (somente admin).

### Antes do evento

- Exporte uma ficha PDF individual ou todas as combinações equipe/avaliador em ZIP. Imprima em A4, escala 100%, sem ajuste.
- São 3 autorizados (A1 a A3), 2 desconhecidos (D1 e D2), três notas C1–C3 e o uso de câmeras.
- Distribua as fichas antes do NEXT. A coleta em papel independe de conexão à internet.

### Após o retorno da internet

- A coordenação seleciona equipe/avaliador e fotografa a folha inteira (quatro marcas pretas visíveis).
- O servidor tenta ler as bolinhas com Pillow (OMR). Marcações ambíguas ou ausentes ficam pendentes de correção.
- A fotografia é armazenada em bucket PRIVADO do Supabase. O administrador confere cada campo e transcreve observações manuscritas.
- A nota somente é contabilizada após a confirmação explícita do admin. Uma nota anterior não é sobrescrita sem digitar SUBSTITUIR.
- Notas importadas passam a compor o mesmo ranking e geram registro de auditoria e comprovante.

### Apagar histórico de notas

- A coordenação pode excluir notas contabilizadas de uma equipe ou de todas com **uma única confirmação** ao clicar em Apagar. A sessão administrativa e o CSRF protegem a operação; não é necessário inserir novamente a senha nem digitar uma frase.
- O backup CSV é **opcional** e não impede a exclusão. A exclusão NÃO pode ser desfeita automaticamente.
- Os comprovantes fotográficos e a auditoria são mantidos como trilha de responsabilidade; usuários e temporizadores não são apagados.

### Passo obrigatório no Supabase existente

Execute uma vez o SQL em [supabase/migrations/20261012_contingencia_e_historico.sql](supabase/migrations/20261012_contingencia_e_historico.sql) no SQL Editor do projeto NEXT (referência iwfqmdsrourtdvrgiums). O script cria tabela de importações, bucket privado e duas funções RPC. NÃO execute novamente a criação de usuários.

### Limitações

- A fotografia deve seguir o formulário padronizado N2026-OMR1. O sistema lê círculos preenchidos e não faz OCR de textos livres.
- A leitura pode falhar em sombras ou perspectiva forte. A revisão humana é obrigatória antes de somar qualquer nota.
- O aplicativo depende da internet para importar; apenas o papel funciona durante o período offline.
- Equipe bloqueada deve ser desbloqueada temporariamente pela coordenação antes da importação e bloqueada novamente.

## Segurança

- Supabase Data API usa segredo de servidor, jamais uma chave pública.
- Tabelas com RLS ativado sem políticas públicas; somente service_role acessa.
- RPCs restritas a service_role garantem atualização atômica do tempo e das avaliações.
- Senhas com hash, cookies HTTPOnly, proteção CSRF e bloqueio temporário após tentativas malsucedidas.
- Evite divulgar links administrativos antes da liberação oficial.

## Execução local

Instale Python 3.12 e use um ambiente virtual:

~~~bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Configure no terminal SUPABASE_URL, SUPABASE_SECRET_KEY, SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD
python app.py
~~~

Abra http://localhost:5000. O ambiente local também usa o projeto Supabase (sem SQLite).
Para rodar testes simulados da API, instale pytest e rode pytest -q.

## Solução de problemas

- /health retorna HTTP 503 e menciona variáveis: complete os segredos no Vercel e faça Redeploy.
- /health indica schema ausente: execute [supabase/schema.sql](supabase/schema.sql) no SQL Editor do projeto correto.
- /login funciona, mas não salva: confirme as funções RPC e respectivas permissões; aguarde atualização do cache da API.
- Teste com dois celulares, crie avaliadores, salve duas notas e exporte CSV antes do evento.

Fontes: [Supabase API Keys](https://supabase.com/docs/guides/getting-started/api-keys), [Supabase Data API](https://supabase.com/docs/guides/api), [Vercel Flask](https://vercel.com/docs/frameworks/backend/flask).

## Quatro avaliadores oficiais (12/10/2026)

A banca agora dispõe de apenas quatro perfis: avaliador01 (DATEN), avaliador02 (SVATECH), avaliador03 (Prof. Luiz, FIAP) e avaliador04 (Prof. Roberto, FIAP). Coordenação é acesso separado, não conta como avaliador.

O login, gerenciamento de contas, importação manual e ranking consideram somente esses quatro avaliadores. Qualquer nota antiga do quinto perfil permanece armazenada para auditoria, mas não compõe a média oficial.

Execute no SQL Editor do Supabase do NEXT a migração [20261012_quatro_avaliadores.sql](supabase/migrations/20261012_quatro_avaliadores.sql) para desativar a conta avaliador05 sem apagá-la. O aplicativo já impede novos acessos desse usuário mesmo antes da migração.

## Avaliação rápida, sem observações, e ponderação por câmera (12/10/2026)

- A ficha eletrônica não possui mais a caixa de **Observações técnicas**. Continuam obrigatórios os cinco participantes, três critérios C1/C2/C3 (0 a 5), câmeras disponibilizadas e utilizadas. A coluna histórica de notas é preservada para compatibilidade com fichas antigas e contingência.
- **Uma câmera utilizada:** bônus de 10% no total técnico, com limite de 15 pontos. **Duas câmeras utilizadas:** sem bônus. Fórmula: `nota ponderada = min(15, (C1+C2+C3) * 1.10)` se usar uma câmera; caso contrário, `nota ponderada = C1+C2+C3`.
- Exemplo: 8/15 com uma câmera corresponde a **8,80/15** no ranking; com duas câmeras, **8,00/15**.
- O ranking usa a **média das notas ponderadas dos quatro avaliadores oficiais**. A ficha exibe nota técnica e nota ponderada. O quadro de classificação mostra ambas as médias e quantas fichas declararam uso de uma câmera.
- O CSV exporta `total_bruto`, `total_ponderado` e `bonus_uma_camera_pct`. Registros existentes também recebem essa ponderação automaticamente pelo número de câmeras armazenado, sem modificar o banco.
- **Instalação obrigatória:** executar no SQL Editor do Supabase do NEXT 2026 a migração [supabase/migrations/20261012_sem_observacoes_bonus_camera.sql](supabase/migrations/20261012_sem_observacoes_bonus_camera.sql). Ela atualiza a função RPC de salvamento, inclusive removendo a exigência antiga de A4. Nenhuma tabela ou usuário é apagado.
- As regras de pontuação precisam ser confirmadas e comunicadas à banca antes da competição, pois alteram o ranking comparativamente às notas técnicas brutas.

### Correção se aparecer erro ao limpar o histórico

A instalação inicial de contingência pode ter deixado a função de exclusão ausente.
Execute **somente** [supabase/migrations/20261012_corrigir_limpeza_historico.sql](supabase/migrations/20261012_corrigir_limpeza_historico.sql) no SQL Editor do projeto NEXT 2026.
Este script apenas cria/atualiza a função administrativa, concede permissões à chave privada do servidor e recarrega o cache PostgREST; **não apaga avaliações ao ser executado**. A remoção continua exigindo o comando do administrador autenticado na aplicação, com confirmação única. A interface passa a mostrar erros específicos em vez do aviso genérico.

### Correção definitiva da exclusão de todas as notas (SQLSTATE 21000)

O Supabase deste projeto rejeita `DELETE FROM public.banca_avaliacoes;` sem `WHERE`.
Execute uma vez [20261013_corrigir_delete_com_where.sql](supabase/migrations/20261013_corrigir_delete_com_where.sql)
no SQL Editor **do projeto NEXT 2026**. A migração apenas atualiza a função administrativa; **não apaga avaliações ao ser executada**.

Após a migração, no painel da coordenação, a escolha **TODAS AS NOTAS** usa um `DELETE` com cláusula `WHERE`, abrangendo apenas as equipes cadastradas. A escolha de um único grupo usa o mesmo filtro, restrito ao grupo. A operação segue protegida pela sessão do administrador, uma confirmação e auditoria, e o backup CSV é opcional.


## Câmeras disponibilizadas: sempre 2 (13/10/2026)

Para todos os grupos, **o sistema disponibiliza exatamente duas câmeras**, sendo essa informação fixa e não editável na ficha digital, na revisão de fotografias e nos formulários PDF de contingência. O avaliador informa somente **quantas utilizou (1 ou 2)**. Utilizar uma câmera mantém o bônus de 10%, limitado a 15 pontos.

O servidor Flask ignora qualquer valor `available` enviado pelo navegador e grava `p_disponiveis=2` também nas importações manuais. Não é necessário modificar o Supabase para salvar novas fichas. Dados históricos que tenham sido preenchidos com "1 disponibilizada" podem ser normalizados **opcionalmente**, sem alterar notas ou câmeras efetivamente usadas, executando [20261013_fixar_duas_cameras_disponiveis.sql](supabase/migrations/20261013_fixar_duas_cameras_disponiveis.sql) no Supabase NEXT 2026. A migração também protege contra novos registros com valor diferente de 2.

## Entrada direta por perfil (20/10/2026)

A página `/` abre diretamente a área dos **Avaliadores**. As outras duas rotas também funcionam sem uma etapa anterior de login: `/avaliador` e `/coordenacao` (Scrum Master / Coordenação). A antiga `/login` foi mantida por compatibilidade e exibe a mesma interface integrada.

- **Avaliadores:** selecione exclusivamente um dos quatro perfis oficiais com *checkbox*. A interface desmarca automaticamente os demais, e o servidor rejeita submissões com seleção ausente ou duplicada. A senha individual é informada no próprio painel, sem tela adicional. Após a verificação, o avaliador entra diretamente no quadro com as nove equipes e seus formulários. Notas e sessão continuam associadas ao usuário autenticado no Supabase.
- **Scrum Master / Coordenação:** aba separada com apenas a senha administrativa, conduz ao painel de cronômetro, ranking, exportações e exclusão controlada. Os privilégios administrativos não são liberados pela seleção visual.
- As páginas públicas de entrada não consultam o Supabase, permitindo apresentar a interface quando o projeto estiver pausado. Para entrar nas áreas autenticadas e salvar notas, entretanto, o projeto Supabase NEXT precisa estar ativo.

Sem mudanças em tabelas ou migrações SQL.

## Acesso sem senha para a banca (20/10/2026)

Os quatro avaliadores agora acessam sem senha: selecionam um único **checkbox** com seu nome em `/` ou `/avaliador` e pressionam **Começar a avaliar**. O servidor aceita somente perfis de avaliador cadastrados e ativos e cria uma sessão associada ao ID selecionado. Não há mudança nas notas, pontuações ou tabelas.

A **Coordenação / Scrum Master** segue exigindo senha em `/coordenacao`, com bloqueio de tentativas inválidas e proteções administrativas. A escolha de um nome de avaliador não desbloqueia recursos administrativos.

**Atenção à integridade:** não há autenticação de identidade dos avaliadores sem senha. Qualquer pessoa que tenha acesso ao link pode selecionar outro avaliador e alterar suas notas. Compartilhe o endereço apenas com a banca e mantenha a coordenação monitorando a classificação. O banco Supabase deve estar ativo para o fluxo funcionar.
