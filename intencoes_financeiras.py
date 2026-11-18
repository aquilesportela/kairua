"""Diário local da UI, sem SQLite e sem efeitos financeiros.

Um JSON UTF-8 por chave; lock de sistema operacional entre processos, fsync do
temporário e os.replace no mesmo diretório. Locks são liberados pelo SO após
interrupção. Não usar em compartilhamentos de rede/sincronização de arquivos.
O vínculo é ao caminho absoluto configurado, não à identidade física do banco:
trocar/restaurar o arquivo nesse caminho exige preservar e reconciliar o diário.
Não remover intenções incertas. Backup deve incluir este diretório.
"""
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

import banco
import servicos_financeiros as sf


class ErroIntencao(Exception):
    """Falha local: não autoriza criar outra chave nem afirmar sucesso."""


# Catálogo da interface, não de todos os serviços do motor. Não usar getattr
# sobre nomes recebidos do JSON. Envelope e versão 1 da 3.3B são preservados.
_PERFIS = {
    'registrar_evento_manual': ('registrar_evento', ('data_competencia', 'data_vencimento'), (1, 0, 0, 0, 0, 0)),
    'registrar_operacao_imediata': ('registrar_imediata',
        ('data_competencia', 'data_vencimento', 'data_liquidacao'), (1, 1, 1, 0, 0, 0)),
}
_CAMPOS_IDS = ('evento_ids', 'lancamento_ids', 'liquidacao_ids',
               'estorno_ids', 'reversao_ids', 'reclassificacao_ids')


def _perfil(nome):
    if type(nome) is not str or nome not in _PERFIS:
        raise ErroIntencao('Serviço não autorizado no diário da interface.')
    return _PERFIS[nome]


def servico_da_intencao(registro):
    nome = json.loads(registro['payload'])['servico']
    _perfil(nome)
    return nome


def destino_configurado():
    # Resolução lexical: não abre nem consulta o arquivo financeiro.
    return os.path.normcase(os.path.abspath(banco.obter_caminho_banco()))


def diretorio_padrao():
    raiz = os.environ.get('LOCALAPPDATA')
    raiz = Path(raiz) if raiz else Path.home() / '.local' / 'share'
    identificador = sha256(destino_configurado().encode('utf-8')).hexdigest()
    return raiz / 'Kairua' / 'intencoes' / identificador


def parametros_da_intencao(registro):
    p = json.loads(registro['payload'])['parametros']
    for campo in _perfil(servico_da_intencao(registro))[1]:
        p[campo] = sf.interpretar_data_iso(p[campo])
    return p


def _json(dados):
    return json.dumps(dados, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def conferir_recibo(recibo, chave, *, nome_servico='registrar_evento_manual'):
    tipo, _, contagens = _perfil(nome_servico)
    if (type(recibo) is not sf.ResultadoOperacao or recibo.chave != chave
            or recibo.tipo_operacao != tipo
            or type(recibo.versao_contrato) is not int or recibo.versao_contrato != 1
            or type(recibo.operacao_id) is not int or not 1 <= recibo.operacao_id <= sf.MAX_CENTAVOS):
        raise ErroIntencao('Recibo incompatível com a intenção registrada.')
    for campo, quantidade in zip(_CAMPOS_IDS, contagens):
        ids = getattr(recibo, campo)
        if (type(ids) is not tuple or len(ids) != quantidade
                or any(type(i) is not int or not 1 <= i <= sf.MAX_CENTAVOS for i in ids)):
            raise ErroIntencao('Cardinalidade ou identificador incompatível no recibo.')
    return asdict(recibo)


class ArmazenamentoIntencoes:
    def __init__(self, diretorio=None):
        self.diretorio = Path(diretorio) if diretorio is not None else diretorio_padrao()
        self.destino = destino_configurado()

    @contextmanager
    def _bloqueio(self, nome):
        self.diretorio.mkdir(parents=True, exist_ok=True)
        # Nunca substituir ou apagar o arquivo de lock: todas as sessões
        # precisam disputar o mesmo objeto, inclusive após os.replace do JSON.
        with (self.diretorio / nome).open('a+b') as arquivo:
            if os.name == 'nt':
                import msvcrt
                arquivo.seek(0)
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    arquivo.seek(0)
                    msvcrt.locking(arquivo.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)

    def _caminho(self, chave):
        sf.validar_chave(chave)
        return self.diretorio / (chave[10:] + '.json')

    def _validar(self, r):
        try:
            if set(r) != {'versao', 'chave', 'destino', 'payload', 'estado', 'recibo', 'erro'}:
                raise ValueError('Campos inválidos')
            if type(r['versao']) is not int or r['versao'] != 1 or r['destino'] != self.destino:
                raise ValueError('Versão ou destino incompatível')
            nome_servico = servico_da_intencao(r)
            req = sf.canonicalizar_requisicao(nome_servico, chave=r['chave'],
                                              **parametros_da_intencao(r))
            if req.requisicao_canonica != r['payload']:
                raise ValueError('Payload não canônico')
            if r['estado'] not in ('pendente', 'incerta', 'confirmada', 'rejeitada'):
                raise ValueError('Estado inválido')
            if r['erro'] is not None and type(r['erro']) is not str:
                raise ValueError('Erro inválido')
            if r['estado'] in ('pendente', 'confirmada') and r['erro'] is not None:
                raise ValueError('Estado incompatível com erro')
            if r['estado'] == 'rejeitada' and not r['erro']:
                raise ValueError('Rejeição sem motivo')
            if r['estado'] == 'confirmada':
                campos = dict(r['recibo'])
                for k in ('evento_ids', 'lancamento_ids', 'liquidacao_ids', 'estorno_ids',
                          'reversao_ids', 'reclassificacao_ids'):
                    campos[k] = tuple(campos[k])
                conferir_recibo(sf.ResultadoOperacao(**campos), r['chave'], nome_servico=nome_servico)
            elif r['recibo'] is not None:
                raise ValueError('Recibo sem confirmação')
            return r
        except (ValueError, TypeError, KeyError, sf.ErroFinanceiro) as erro:
            raise ErroIntencao('Intenção corrompida ou incompatível; arquivo preservado.') from erro

    def _ler(self, chave):
        try:
            with self._caminho(chave).open(encoding='utf-8') as arquivo:
                r = self._validar(json.load(arquivo))
        except (json.JSONDecodeError, UnicodeError) as erro:
            raise ErroIntencao('Arquivo de intenção corrompido; conteúdo preservado.') from erro
        if r['chave'] != chave:
            raise ErroIntencao('Chave do arquivo não corresponde ao conteúdo.')
        return r

    def _gravar(self, r):
        self._validar(r)
        temporario = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                    prefix='.intencao-', suffix='.tmp', dir=self.diretorio, delete=False) as f:
                temporario = Path(f.name)
                f.write(_json(r) + '\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporario, self._caminho(r['chave']))
            if os.name != 'nt':
                fd = os.open(self.diretorio, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            if temporario is not None:
                temporario.unlink(missing_ok=True)

    def criar(self, *, chave, servico='registrar_evento_manual', **parametros):
        _perfil(servico)
        req = sf.canonicalizar_requisicao(servico, chave=chave, **parametros)
        with self._bloqueio('.diario.lock'):
            if self._caminho(chave).exists():
                r = self._ler(chave)
                if r['payload'] != req.requisicao_canonica:
                    raise sf.ConflitoIdempotencia('Chave local já vinculada a outra intenção.')
                return r
            r = dict(versao=1, chave=chave, destino=self.destino,
                     payload=req.requisicao_canonica, estado='pendente', recibo=None, erro=None)
            self._gravar(r)
            return r

    def obter(self, chave):
        with self._bloqueio('.diario.lock'):
            return self._ler(chave)

    def listar_pendentes(self):
        with self._bloqueio('.diario.lock'):
            registros = [self._ler('kairua:v1:' + p.stem)
                         for p in sorted(self.diretorio.glob('*.json'))]
            return [r for r in registros if r['estado'] in ('pendente', 'incerta')]

    def _atualizar(self, chave, **mudancas):
        with self._bloqueio('.diario.lock'):
            r = self._ler(chave)
            self._gravar(r | mudancas)

    def executar(self, chave, *, servico=None):
        """Reexecuta só esta intenção, serializando tentativas da mesma chave.

        Incerta é gravada ANTES da chamada. Se o processo morrer, o payload
        permanece recuperável. Não existe transação distribuída JSON/SQLite:
        falha após commit é recuperada pelo replay do serviço aprovado.
        """
        if destino_configurado() != self.destino:
            raise ErroIntencao('Banco configurado mudou; recuperação bloqueada.')
        sf.validar_chave(chave)
        with self._bloqueio('.exec-' + chave[10:] + '.lock'):
            r = self.obter(chave)
            if destino_configurado() != self.destino:
                raise ErroIntencao('Banco configurado mudou durante a recuperação.')
            nome_servico = servico_da_intencao(r)
            # A injeção de callable é preservada para os testes de falha. Na
            # produção o despacho é fechado e vem da intenção, não do menu.
            executar = servico
            if executar is None:
                executar = (sf.registrar_evento_manual if nome_servico == 'registrar_evento_manual'
                            else sf.registrar_operacao_imediata)
            if r['estado'] == 'rejeitada':
                raise ErroIntencao('Intenção rejeitada definitivamente: ' + r['erro'])
            confirmado = r['estado'] == 'confirmada'
            if not confirmado:
                self._atualizar(chave, estado='incerta', erro=None)
            try:
                recibo = executar(chave=chave, **parametros_da_intencao(r))
                serializado = conferir_recibo(recibo, chave, nome_servico=nome_servico)
                if confirmado and _json(serializado) != _json(r['recibo']):
                    raise ErroIntencao('Recibo recuperado diverge do recibo confirmado.')
            except Exception as erro:
                definitivos = (sf.ParametroInvalido, sf.CategoriaInexistente,
                               sf.CategoriaIncompativel, sf.IdentificadoresEsgotados,
                               sf.EsquemaIncompativel)
                # Um erro na recuperação não prova que uma tentativa anterior
                # não confirmou. Nunca rebaixar confirmação nem descartar dúvida.
                if not confirmado:
                    estado = 'rejeitada' if r['estado'] == 'pendente' and isinstance(erro, definitivos) else 'incerta'
                    self._atualizar(chave, estado=estado, erro=type(erro).__name__)
                raise
            if not confirmado:
                self._atualizar(chave, estado='confirmada', recibo=serializado, erro=None)
            return recibo
