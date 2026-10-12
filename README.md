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
- Identificação dos participantes A1–A4 e D1–D2.
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
