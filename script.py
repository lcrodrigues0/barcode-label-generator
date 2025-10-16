import barcode
import csv
from barcode.writer import ImageWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4


# Configuração de layout
largura_pagina, altura_pagina = A4
margem_esquerda = 100
margem_superior = 750
espaco_vertical = 100  # Espaço entre os códigos de barras

# Criar o PDF
pdf_path = "codigos_barras.pdf"
c = canvas.Canvas(pdf_path, pagesize=A4)
c.setFont("Helvetica-Bold", 12)

y = margem_superior

# Lê os códigos do arquivo CSV
# Abre o CSV e lê cada linha
with open('codigos.csv', newline='') as csvfile:
    leitor = csv.reader(csvfile)

    for linha in leitor:
        codigo_num = linha[0].strip()

        # Gerar imagem temporária do código
        codigo = barcode.get("code128", codigo_num, writer=ImageWriter())
        img_filename = f"tmp_{codigo_num}"
        codigo.save(img_filename)

        print(img_filename)

        # Desenhar o código no PDF
        c.drawImage(f'{img_filename}.png', margem_esquerda, y, width=150, height=80)

        y -= espaco_vertical

        # Quebra de página se necessário
        if y < 100:
            c.showPage()
            y = margem_superior

# Finaliza o PDF
c.save()
print(f"✅ PDF gerado com sucesso: {pdf_path}")