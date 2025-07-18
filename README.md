# AmbientLed Home Assistant Integration

Integracja AmbientLed dla Home Assistant umożliwiająca sterowanie oświetleniem LED przez WebSocket.

## Instalacja

1. Skopiuj folder `custom_components/ambientled` do katalogu `config/custom_components/` w Twoim Home Assistant
2. Uruchom ponownie Home Assistant
3. Przejdź do **Konfiguracja** > **Urządzenia i usługi** > **Dodaj integrację**
4. Wyszukaj "AmbientLed" i dodaj integrację
5. Wprowadź swój token użytkownika z panelu AmbientLed

## Konfiguracja

### Token użytkownika

Token można znaleźć w panelu AmbientLed w ustawieniach konta.

### URL WebSocket (opcjonalne)

Domyślnie: `wss://ambientled.pl`
Zmień tylko jeśli używasz własnego serwera AmbientLed.

## Rozwiązywanie problemów

### Problem: "WebSocket connection closed" / "Not connected to WebSocket"

#### Przyczyny:

1. **Duplikowanie połączeń WebSocket** - integracja tworzyła wiele połączeń
2. **Brak właściwego zarządzania stanem połączenia**
3. **Problemy z rekonfiguracją** - stare połączenia nie były prawidłowo zamykane

#### Rozwiązania:

##### 1. Sprawdź logi Home Assistant

```bash
# W Home Assistant > Developer Tools > Logs
# Szukaj komunikatów:
# - "WebSocket connection closed"
# - "Not connected to WebSocket"
# - "No devices found or failed to get devices"
```

##### 2. Zrestartuj integrację

1. Przejdź do **Konfiguracja** > **Urządzenia i usługi**
2. Znajdź integrację AmbientLed
3. Kliknij **Konfiguruj**
4. Kliknij **Usuń integrację**
5. Dodaj integrację ponownie

##### 3. Sprawdź połączenie sieciowe

- Upewnij się, że Home Assistant ma dostęp do internetu
- Sprawdź czy serwer AmbientLed jest dostępny: `wss://ambientled.pl`

##### 4. Sprawdź token

- Upewnij się, że token jest aktualny
- Sprawdź czy token ma odpowiednie uprawnienia

### Problem: "No devices found"

#### Przyczyny:

1. Brak urządzeń w koncie AmbientLed
2. Urządzenia są offline
3. Problem z autoryzacją

#### Rozwiązania:

1. Sprawdź czy masz urządzenia w panelu AmbientLed
2. Upewnij się, że urządzenia są online
3. Sprawdź czy token ma dostęp do urządzeń

### Problem: "Authentication failed"

#### Rozwiązania:

1. Sprawdź czy token jest poprawny
2. Wygeneruj nowy token w panelu AmbientLed
3. Upewnij się, że token nie wygasł

## Logi debugowania

Aby włączyć szczegółowe logi:

1. Przejdź do **Konfiguracja** > **Ustawienia** > **System** > **Logs**
2. Dodaj do konfiguracji:

```yaml
logger:
  default: info
  logs:
    custom_components.ambientled: debug
```

## Struktura plików

```
custom_components/ambientled/
├── __init__.py          # Główna konfiguracja integracji
├── config_flow.py       # Konfiguracja przez UI
├── const.py            # Stałe
├── light.py            # Implementacja świateł LED
├── manifest.json       # Metadane integracji
└── logo.png           # Logo integracji
```

## Najnowsze zmiany

### v0.1.1 - Naprawa problemów z WebSocket

- ✅ Naprawiono duplikowanie połączeń WebSocket
- ✅ Dodano właściwe zarządzanie stanem połączenia
- ✅ Poprawiono logikę rekonfiguracji
- ✅ Dodano lepsze logowanie dla debugowania
- ✅ Naprawiono deprecation warning dla SUPPORT_EFFECT
- ✅ Dodano cleanup połączeń przy unload integracji

### v0.1.0 - Pierwsza wersja

- Podstawowa funkcjonalność sterowania światłami LED
- Obsługa kolorów, jasności i efektów
- Połączenie przez WebSocket

## Wsparcie

W przypadku problemów:

1. Sprawdź logi Home Assistant
2. Upewnij się, że używasz najnowszej wersji
3. Sprawdź czy serwer AmbientLed jest dostępny
4. Skontaktuj się z autorem integracji

## Autor

Marcin Szarmach - @marcinszarmach
