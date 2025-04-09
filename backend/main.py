import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import openai
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Configuración OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuración Supabase
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
)

# FastAPI
app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prompt del sistema
system_prompt_sql = """
Sos un asistente que responde preguntas sobre el menú de un restaurante. Tenés acceso a una base de datos con la tabla 'restaurant_menu' que tiene estas columnas:

- id: uuid
- name: texto (nombre del plato)
- category: texto (puede ser 'entrada', 'principal' o 'postre')
- description: texto (descripción del plato)
- price: número (precio del plato)
- tags: array de texto (por ejemplo: ['vegano'], ['sin gluten'])

Si una pregunta requiere datos específicos (como nombres de platos, cantidad, precios, categorías, etc), primero generá una **consulta SQL en PostgreSQL**, sin inventar la respuesta.

**NO inventes nombres de platos ni números.**

El formato de tu respuesta debe ser:

SQL: SELECT ...;

Respuesta: [una respuesta tentativa que será completada por los datos]
"""

@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    user_message = body.get("message")

    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt_sql},
            {"role": "user", "content": user_message}
        ],
        temperature=0,
    )

    response_text = completion.choices[0].message["content"].strip()
    print("🧠 Respuesta del modelo:", response_text)

    if response_text.startswith("SQL:"):
        try:
            sql_part = response_text.split("SQL:")[1].split("Respuesta:")[0].strip()

            if sql_part.endswith(";"):
                sql_part = sql_part[:-1].strip()

            print("🧠 SQL detectada:", sql_part)

            db_response = supabase.rpc("execute_sql", {"query": sql_part}).execute()

            if hasattr(db_response, "error") and db_response.error:
                return {
                    "error": str(db_response.error),
                    "sql_query": sql_part,
                    "message": "Ocurrió un error al ejecutar la consulta."
                }

            if db_response.data:
                data = db_response.data

                # Generar una respuesta según los campos presentes
                if all("name" in d and "price" in d and "description" in d for d in data):
                    respuesta = "Estos son los platos disponibles:\n\n"
                    for item in data:
                        respuesta += f"- {item['name']}: {item['description']} (${item['price']})\n"
                elif all("name" in d for d in data):
                    nombres = ", ".join(d["name"] for d in data)
                    respuesta = f"Los platos disponibles son: {nombres}."
                elif all("count" in d for d in data):
                    respuesta = f"Hay {data[0]['count']} elementos que cumplen con esa condición."
                else:
                    respuesta = f"Resultados obtenidos: {data}"

                return {
                    "message": respuesta,
                    "results": data,
                    "sql_query": sql_part
                }

            return {
                "message": "No se encontraron resultados.",
                "results": [],
                "sql_query": sql_part
            }

        except Exception as e:
            return {
                "error": f"Error al procesar la respuesta del modelo: {str(e)}",
                "raw_response": response_text
            }

    else:
        return {
            "message": response_text,
            "results": None,
            "sql_query": None
        }
