<!DOCTYPE html>
<html lang="pl">
<head>
    <title>{{ car.marka }} {{ car.model }} - Giełda Radom</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
    <style>
        :root { --radom-red: #ce2b37; }
        .car-img { border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); width: 100%; object-fit: cover; }
        .price-tag { color: var(--radom-red); font-size: 2.5rem; font-weight: 800; }
        .spec-box { background: white; padding: 20px; border-radius: 15px; border-left: 5px solid var(--radom-red); }
    </style>
</head>
<body class="bg-light">
    <nav class="navbar navbar-dark bg-dark mb-4">
        <div class="container"><a class="navbar-brand fw-bold" href="/">Giełda Radom</a></div>
    </nav>

    <div class="container mb-5">
        <div class="row">
            <div class="col-lg-7">
                <img src="{{ car.img }}" class="car-img mb-4" alt="{{ car.marka }}">
                <div class="bg-white p-4 rounded-4 shadow-sm">
                    <h4 class="fw-bold mb-3">Opis pojazdu</h4>
                    <p style="white-space: pre-line;">{{ car.opis }}</p>
                </div>
            </div>
            <div class="col-lg-5">
                <div class="spec-box shadow-sm mb-4">
                    <h1 class="fw-bold">{{ car.marka }} {{ car.model }}</h1>
                    <p class="text-muted">{{ car.rok }} r. | {{ car.przebieg }} km</p>
                    <div class="price-tag mb-3">{{ car.cena|int }} PLN</div>
                    <hr>
                    <div class="d-grid gap-2">
                        <a href="tel:{{ car.telefon }}" class="btn btn-success btn-lg rounded-pill">
                            <i class="bi bi-telephone-fill me-2"></i> {{ car.telefon }}
                        </a>
                        <a href="{{ url_for('toggle_favorite', car_id=car.id) }}" class="btn btn-outline-danger rounded-pill">
                            <i class="bi bi-heart"></i> Dodaj do ulubionych
                        </a>
                    </div>
                </div>

                <div class="bg-dark text-white p-4 rounded-4 shadow-sm">
                    <h5 class="mb-3"><i class="bi bi-info-circle"></i> Szczegóły</h5>
                    <div class="d-flex justify-content-between mb-2"><span>Paliwo:</span><strong>{{ car.paliwo }}</strong></div>
                    <div class="d-flex justify-content-between mb-2"><span>Skrzynia:</span><strong>{{ car.skrzynia }}</strong></div>
                    <div class="d-flex justify-content-between mb-2"><span>Wyświetlenia:</span><strong>{{ car.wyswietlenia }}</strong></div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
