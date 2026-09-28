from backend.app import create_app
from backend.controllers.instrutor_controller import EditInstrutorForm

app = create_app()
with app.app_context():
    print("Choices for posto_categoria:")
    print(EditInstrutorForm.posto_categoria.kwargs['choices'])
    
    # We can't easily fake a request without test_client, let's use it
    client = app.test_client()
    # We don't have login, but we can just inspect the form object