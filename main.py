// **formulario de registro
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'dart:io';
import '../core/validators.dart';
import '../widgets/document_row.dart';
//import 'package:app_tesis_ug/widgets/custom_button.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';

class RegisterForm extends StatefulWidget {
  const RegisterForm({super.key});

  @override
  State<RegisterForm> createState() => _RegisterFormState();
}

class _RegisterFormState extends State<RegisterForm> {
  final PageController _pageController = PageController();
  int _currentPage = 0;

  final _nameController = TextEditingController();
  final _lastnameController = TextEditingController();
  final _emailController = TextEditingController();
  final _phoneController = TextEditingController();
  final _passwordController = TextEditingController();
  final _password2Controller = TextEditingController();

  String _country = 'Ecuador';
  String _city = 'Guayaquil';
  DateTime? _birthDate;

  final String _role = 'Cliente';

  File? _cedulaFrontFile;
  File? _cedulaBackFile;
  File? _selfieFile;
  final ImagePicker _picker = ImagePicker();

  // **Variables para controlar la visibilidad de la contraseña
  bool _isPasswordVisible = false;
  bool _isPassword2Visible = false;

  final Map<String, List<String>> _citiesByCountry = {
    'Ecuador': ['Guayaquil', 'Quito', 'Cuenca', 'Machala'],
    'Estados Unidos': ['New York', 'Los Angeles', 'Miami'],
    'España': ['Madrid', 'Barcelona', 'Valencia'],
    'México': ['Ciudad de México', 'Guadalajara', 'Monterrey'],
    'Alemania': ['Berlín', 'Múnich', 'Hamburgo'],
    'Inglaterra': ['Londres', 'Manchester', 'Birmingham'],
    'Turquía': ['Estambul', 'Ankara', 'Esmirna'],
    'Corea': ['Seúl', 'Busan', 'Incheon'],
    'Argentina': ['Buenos Aires', 'Córdoba', 'Rosario'],
    'Colombia': ['Bogotá', 'Medellín', 'Cali'],
    'Perú': ['Lima', 'Arequipa', 'Cusco'],
  };

  final Map<String, String> _countryPhoneCodes = {
    'Ecuador': '+593',
    'Estados Unidos': '+1',
    'España': '+34',
    'México': '+52',
    'Alemania': '+49',
    'Inglaterra': '+44',
    'Turquía': '+90',
    'Corea': '+82',
    'Argentina': '+54',
    'Colombia': '+57',
    'Perú': '+51',
  };

  // **Función que obtiene la lada del país seleccionado
  String _getCountryPhoneCode(String country) {
    return _countryPhoneCodes[country] ??
        ''; // ?Si no existe el país, retorna un string vacío
  }

  // **Función para seleccionar una imagen desde la galería
  Future<void> _pickImageFile(Function(File) onPicked) async {
    final picked = await _picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 85,
    );
    if (picked != null) {
      onPicked(File(picked.path));
      setState(() {});
    }
  }

  // !Validadores simples
  bool _validateEmail(String email) => validateEmail(email);
  String? _validatePassword(String password) => validatePassword(password);
  bool _validatePhone(String phone) => validatePhone(phone);

  // **Avanzar a la siguiente página
  void _nextPage() {
    FocusScope.of(context).unfocus();
    if (_currentPage < 1) {
      _pageController.nextPage(
        duration: const Duration(milliseconds: 300),
        curve: Curves.ease,
      );
    }
  }

  // **Regresar a la página anterior
  void _prevPage() {
    FocusScope.of(context).unfocus();
    if (_currentPage > 0) {
      _pageController.previousPage(
        duration: const Duration(milliseconds: 300),
        curve: Curves.ease,
      );
    }
  }

  // **Enviar el formulario
  // El botón "Registrarse" llama a esta función
  void _submitFormularioApi() {
    final name = _nameController.text.trim();
    final lastname = _lastnameController.text.trim();
    final email = _emailController.text.trim();
    final pwd = _passwordController.text;
    final pwd2 = _password2Controller.text;
    final phoneLocal = _phoneController.text.trim();

    //** Validaciones generales
    if (name.isEmpty || lastname.isEmpty) {
      _showMessage('Completa nombres y apellidos');
      _pageController.jumpToPage(0);
      return;
    }

    if (!_validateEmail(email)) {
      _showMessage('Correo inválido');
      _pageController.jumpToPage(0);
      return;
    }

    final pwdError = _validatePassword(pwd);
    if (pwdError != null) {
      _showMessage('Contraseña inválida: $pwdError');
      _pageController.jumpToPage(0);
      return;
    }

    if (pwd != pwd2) {
      _showMessage('Las contraseñas no coinciden');
      _pageController.jumpToPage(0);
      return;
    }

    if (pwd.length > 70) {
      _showMessage('La contraseña es demasiado larga (máx. 70 caracteres)');
      _pageController.jumpToPage(0);
      return;
    }

    if (!_validatePhone(phoneLocal)) {
      _showMessage('Teléfono inválido');
      _pageController.jumpToPage(0);
      return;
    }

    // **Validaciones adicionales según el rol
    if (_country.isEmpty || _city.isEmpty || _birthDate == null) {
      _showMessage('Selecciona país, ciudad y fecha de nacimiento');
      _pageController.jumpToPage(0);
      return;
    }

    if (_cedulaFrontFile == null ||
        _cedulaBackFile == null ||
        _selfieFile == null) {
      _showMessage('Sube identificacion y selfie ');
      _pageController.jumpToPage(1);
      return;
    }

    //** BD FECH en formato que API entiende
    String fechaNacimientoFormateada = _birthDate != null
        ? _birthDate!.toIso8601String().split('T')[0]
        : "";

    String fullphone = '${_getCountryPhoneCode(_country)}$phoneLocal';

    // ** BD Creamos el "cuerpo" del JSON
    Map<String, dynamic> body = {
      "nombre": "$name $lastname",
      "email": email,
      "password": pwd,
      "role": _role,
      "fecha_nacimiento": fechaNacimientoFormateada,
      "telefono": fullphone,
      "pais": _country,
      "ciudad": _city,
    };

    // --- 3. ENVIAMOS A LA API ---
    _llamarApiParaRegistrar(body);
  }

  // Esta es la función de red que llamamos desde _submitFormularioA_API
  Future<void> _llamarApiParaRegistrar(Map<String, dynamic> body) async {
    // Usamos la URL correcta (127.0.0.1 es lo mismo que localhost)
    const String apiUrl = 'http://127.0.0.1:8000/registrar_usuario';

    try {
      final response = await http.post(
        Uri.parse(apiUrl),
        headers: {'Content-Type': 'application/json; charset=UTF-8'},
        // Convertimos el MAPA (body) a un string JSON
        body: jsonEncode(body),
      );

      // 4. Manejamos la respuesta
      if (response.statusCode == 200) {
        // 200 = OK. El usuario se creó.
        final data = jsonDecode(response.body);
        debugPrint('¡Éxito! Respuesta: $data');

        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('¡Registro exitoso! ID: ${data['nuevo_id']}'),
            ),
          );
        }
        // Aquí podrías navegar a la pantalla de login
        // Navigator.of(context).pop();
      } else {
        // Hubo un error en el servidor (ej: email duplicado, placa duplicada)
        final error = jsonDecode(response.body);
        debugPrint('Error del servidor: ${response.statusCode}');
        debugPrint('Mensaje: $error');
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text('Error: ${error['error']}')));
        }
      }
    } catch (e) {
      // Error de conexión (ej: sin internet, API apagada, IP incorrecta)
      debugPrint('Error de conexión: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Error de conexión. Revisa el servidor.'),
          ),
        );
      }
    }
  }

  // **Función para mostrar mensajes de error
  void _showMessage(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  // **Limpieza de los controladores de texto
  void _resetFields() {
    _nameController.clear();
    _lastnameController.clear();
    _emailController.clear();
    _phoneController.clear();
    _passwordController.clear();
    _password2Controller.clear();

    // **Reseteo del estado de los archivos y selecciones
    setState(() {
      _country = 'Ecuador';
      _city = 'Guayaquil';
      _birthDate = null;
      _cedulaFrontFile = null;
      _cedulaBackFile = null;
      _selfieFile = null;
    });
    _showMessage('Campos limpiados');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Registro de usuario')),
      body: PageView(
        controller: _pageController,
        physics: const NeverScrollableScrollPhysics(), // Evita deslizar
        onPageChanged: (page) => setState(() => _currentPage = page),
        children: [
          _buildPersonalDataPage(), // **Página 0: Datos personales
          _buildDocumentsPage(), // **Página 1: Carga de documentos
        ],
      ),
    );
  }

  // **Página 0: Datos personales
  Widget _buildPersonalDataPage() {
    //return SingleChildScrollView( // <-- Añadido para evitar overflow
    return Padding(
      padding: const EdgeInsets.all(20.0),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Datos Personales',
              style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 20),
            // **Campo para el nombre
            TextField(
              controller: _nameController,
              decoration: const InputDecoration(
                labelText: 'Nombre',
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.person),
              ),
            ),
            const SizedBox(height: 15),

            // **Campo para el apellido
            TextField(
              controller: _lastnameController,
              decoration: const InputDecoration(
                labelText: 'Apellido',
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.person_outline),
              ),
            ),
            const SizedBox(height: 15),

            //**Ubicación
            DropdownButtonFormField<String>(
              value: _country,
              decoration: const InputDecoration(
                labelText: 'País',
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.place),
              ),
              items: _citiesByCountry.keys
                  .map((c) => DropdownMenuItem(value: c, child: Text(c)))
                  .toList(),
              onChanged: (v) {
                setState(() {
                  _country = v!;
                  _city = _citiesByCountry[_country]!.first;
                  //_phoneController.text = _getCountryPhoneCode(_country);
                });
              },
            ),
            const SizedBox(height: 15),

            DropdownButtonFormField<String>(
              value: _city,
              decoration: const InputDecoration(
                labelText: 'Ciudad',
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.location_city),
              ),
              items: _citiesByCountry[_country]!
                  .map((c) => DropdownMenuItem(value: c, child: Text(c)))
                  .toList(),
              onChanged: (v) => setState(() => _city = v!),
            ),
            const SizedBox(height: 15),

            // **Campo para el correo electrónico
            TextField(
              controller: _emailController,
              decoration: const InputDecoration(
                labelText: 'Correo electrónico',
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.mail),
              ),
              keyboardType: TextInputType.emailAddress,
            ),
            const SizedBox(height: 15),

            // ** campo para telefono
            TextField(
              controller: _phoneController,
              decoration: InputDecoration(
                labelText: 'Teléfono',
                border: const OutlineInputBorder(),
                prefixIcon: Container(
                  padding: const EdgeInsets.all(12),
                  margin: const EdgeInsets.only(right: 8),
                  decoration: const BoxDecoration(
                    border: Border(
                      right: BorderSide(color: Colors.grey, width: 1),
                    ),
                  ),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        _getCountryPhoneCode(_country),
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: Colors.black54,
                        ),
                      ),
                    ],
                  ),
                ),
                prefixIconConstraints: const BoxConstraints(
                  minWidth: 60,
                  minHeight: 0,
                  maxHeight: 50,
                ),
              ),
              keyboardType: TextInputType.phone,
            ),
            const SizedBox(height: 15),

            // **Campo para la contraseña
            TextField(
              controller: _passwordController,
              obscureText: !_isPasswordVisible,
              decoration: InputDecoration(
                labelText: 'Contraseña',
                border: const OutlineInputBorder(),
                prefixIcon: Icon(Icons.password),
                suffixIcon: GestureDetector(
                  onTapDown: (_) {
                    setState(() => _isPasswordVisible = true);
                  },
                  onTapUp: (_) {
                    setState(() => _isPasswordVisible = false);
                  },
                  onTapCancel: () {
                    setState(() => _isPasswordVisible = false);
                  },
                  child: Icon(
                    _isPasswordVisible
                        ? Icons.visibility
                        : Icons.visibility_off,
                    color: Colors.grey,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 15),

            // **Campo para confirmar la contraseña
            TextField(
              controller: _password2Controller,
              obscureText: !_isPassword2Visible,
              decoration: InputDecoration(
                labelText: 'Confirmar Contraseña',
                border: const OutlineInputBorder(),
                prefixIcon: Icon(Icons.password_outlined),
                suffixIcon: GestureDetector(
                  onTapDown: (_) {
                    setState(() => _isPassword2Visible = true);
                  },
                  onTapUp: (_) {
                    setState(() => _isPassword2Visible = false);
                  },
                  onTapCancel: () {
                    setState(() => _isPassword2Visible = false);
                  },
                  child: Icon(
                    _isPassword2Visible
                        ? Icons.visibility
                        : Icons.visibility_off,
                    color: Colors.grey,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 15),

            // **Campo para fecha de nacimiento
            const Text(
              'Fecha de Nacimiento:',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w500),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: InputDecorator(
                    decoration: const InputDecoration(
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.calendar_month_rounded),
                      contentPadding: EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 14,
                      ),
                    ),
                    child: Text(
                      _birthDate == null
                          ? 'DD/MM/AAAA'
                          : '${_birthDate!.day}/${_birthDate!.month}/${_birthDate!.year}',
                      style: TextStyle(
                        fontSize: 16,
                        color: _birthDate == null
                            ? Colors.grey.shade600
                            : Colors.black,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 10),

                SizedBox(
                  width: 50,
                  height: 50,
                  child: ElevatedButton(
                    onPressed: () async {
                      final picked = await showDatePicker(
                        context: context,
                        initialDate: DateTime.now(),
                        firstDate: DateTime(1900),
                        lastDate: DateTime.now(),
                      );
                      if (picked != null) setState(() => _birthDate = picked);
                    },
                    style: ElevatedButton.styleFrom(
                      padding: EdgeInsets.zero,
                      backgroundColor: Colors.deepPurple,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                    child: const Icon(
                      Icons.calendar_month,
                      color: Colors.white,
                    ),
                  ),
                ),
              ],
            ),

            const SizedBox(height: 30),

            // **Botones de navegación
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                ElevatedButton(
                  onPressed: _prevPage,
                  child: const Text('Anterior'),
                ),
                ElevatedButton(
                  onPressed: _nextPage,
                  child: const Text('Siguiente'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  // **Página 1: Carga de documentos
  Widget _buildDocumentsPage() {
    return SingleChildScrollView(
      // para evitar overflow
      child: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Documentos Requeridos',
              style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 20),

            //*? Selfie
            DocumentRow(
              title: 'Selfie',
              file: _selfieFile,
              icon: Icons.camera_alt,
              onPressed: () => _pickImageFile((file) => _selfieFile = file),
            ),
            const SizedBox(height: 10),

            // *?Cédula frente
            DocumentRow(
              title: 'Identificacion (frente)',
              file: _cedulaFrontFile,
              icon: Icons.image,
              onPressed: () =>
                  _pickImageFile((file) => _cedulaFrontFile = file),
            ),
            const SizedBox(height: 10),

            //*? Cédula dorso
            DocumentRow(
              title: 'Identificacion (dorso)',
              file: _cedulaBackFile,
              icon: Icons.image,
              onPressed: () => _pickImageFile((file) => _cedulaBackFile = file),
            ),

            const SizedBox(height: 30),

            // **Botones
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                ElevatedButton(
                  onPressed: _prevPage,
                  child: const Text('Anterior'),
                ),

                ElevatedButton(
                  onPressed: _submitFormularioApi,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.green,
                  ),
                  child: const Text('Registrarse'),
                ),
              ],
            ),
            const SizedBox(height: 20),

            //!Boton de limpiar
            SizedBox(
              width: double.infinity,
              child: TextButton(
                onPressed: _resetFields,
                style: TextButton.styleFrom(backgroundColor: Colors.red),
                child: const Text('Limpiar campos'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}


