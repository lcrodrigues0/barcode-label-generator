import barcode
import csv
from barcode.writer import ImageWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import os


# Configuração de layout
largura_pagina, altura_pagina = A4

altura_imagem = 0.8*(1.5 * 28.35)
largura_imagem = 0.8*(5 * 28.35)

margem_esquerda = 7.5
margem_direita = largura_pagina - 100

margem_superior = altura_pagina - 80
margem_inferior = 0

espaco_vertical = 80  # Espaço entre os códigos de barras na vertical
espaco_horizontal = largura_imagem + 5  # Espaço entre os códigos de barras na horizontal

# Entrada
nome_arquivo_csv = "codigos.csv"
nome_do_pdf = "codigos_barras.pdf"
font_type = "Helvetica-Bold" 
font_size = 0.8*10
nome_do_orgao = "MTE - SRTE/ES"

# Criar o PDF
pdf_path = nome_do_pdf
c = canvas.Canvas(pdf_path, pagesize=A4)
c.setFont(font_type, font_size)

y = margem_superior
x = margem_esquerda

# Configura o writer para não escrever o texto
options = {
    "write_text": False  # 👈 remove o número embaixo
}

# Lê os códigos do arquivo CSV
# Abre o CSV e lê cada linha
with open('codigos.csv', newline='') as csvfile:
    leitor = csv.reader(csvfile)

    for linha in leitor:
        # Quebra de página se necessário
        if y < margem_inferior:
            c.showPage()
            c.setFont(font_type, font_size)
            y = margem_superior
            
        codigo_num = linha[0].strip()

        # Gerar imagem temporária do código
        codigo = barcode.get("code128", codigo_num, writer=ImageWriter())
        img_filename = f"tmp_{codigo_num}"
        codigo.save(img_filename, options)

        print(img_filename)

        largura_string_codigo = c.stringWidth(codigo_num, font_type, font_size)
        largura_string_orgao = c.stringWidth(nome_do_orgao, font_type, font_size)

        mt = altura_imagem + 4
        mo = (largura_imagem - largura_string_orgao)/2
        mc = (largura_imagem - largura_string_codigo)/2
        mb = -10

        # Escrever o nome do órgão
        c.drawString(x + mo, y + mt, nome_do_orgao)
        # Desenhar o código no PDF
        c.drawImage(f'{img_filename}.png', x, y, width=largura_imagem, height=altura_imagem)
        # Escrever numero do codigo
        c.drawString(x + mc, y + mb, codigo_num)

        if os.path.exists(f"{img_filename}.png"):
            os.remove(f"{img_filename}.png")
            # print("Arquivo excluído com sucesso!")
        else:
            print("O arquivo não existe.")

        x += espaco_horizontal

        if x > margem_direita:
            y -= espaco_vertical
            x = margem_esquerda

# Finaliza o PDF
c.save()
print(f"✅ PDF gerado com sucesso: {pdf_path}")