// -------------------------------------------------------------
// Plataforma de Cursos SisGEn - Lógica com Backend API (PHP)
// -------------------------------------------------------------

// Variáveis Globais
let globalVideos = [];
let globalLogo = {};
let globalIntro = {};

// 1. DADOS PADRÃO LOCAIS DE FALLBACK
const defaultLogoSettings = {
    type: "text",
    text: "SisG<span>En</span> CURSOS",
    imageUrl: "",
    bannerBgType: "url",
    bannerBgUrl: ""
};

const defaultIntroSettings = {
    logoText: "SisG<span>En</span>",
    subtext: "PLATAFORMA DE CURSOS",
    duration: 3
};

// 2. INICIALIZAÇÃO E CARREGAMENTO
document.addEventListener("DOMContentLoaded", async () => {
    // Inicializa controle de assistidos local (NÃO compartilhado globalmente)
    if (!localStorage.getItem("sisgen_watched")) {
        localStorage.setItem("sisgen_watched", JSON.stringify([]));
    }

    // Carrega os dados globais da API
    await loadDataFromServer();

    // Se estivermos na página principal (alunos)
    if (document.getElementById("intro-screen")) {
        runIntroSequence();
        applyCustomLogo();
        renderAllShelves();
    }
});

// Busca dados da API
async function loadDataFromServer() {
    try {
        const response = await fetch('api.php');
        const data = await response.json();
        
        globalVideos = data.videos || [];
        globalLogo = data.logo || defaultLogoSettings;
        globalIntro = data.intro || defaultIntroSettings;
    } catch (error) {
        console.error("Erro ao carregar dados do servidor:", error);
        globalLogo = defaultLogoSettings;
        globalIntro = defaultIntroSettings;
    }
}

// Salva dados na API
async function saveToServer(action, payload) {
    payload.action = action;
    try {
        const response = await fetch('api.php', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) {
            console.error("Erro na resposta:", await response.text());
            showToast("Erro ao salvar! Você está autenticado?");
            return false;
        }
        return true;
    } catch (e) {
        console.error("Exception:", e);
        showToast("Erro de conexão ao servidor!");
        return false;
    }
}

// 3. INTRO SEQUENCE (ESTILO NETFLIX)
function runIntroSequence() {
    const introSettings = globalIntro;
    
    const introLogo = document.getElementById("intro-logo");
    const introSub = document.querySelector(".intro-subtext");
    const introScreen = document.getElementById("intro-screen");
    
    introLogo.innerHTML = introSettings.logoText;
    introSub.textContent = introSettings.subtext;
    
    const durationMs = introSettings.duration * 1000;
    
    introLogo.style.animationDuration = `${introSettings.duration + 0.5}s`;
    introScreen.style.animation = `fadeOutIntro 0.5s ease ${introSettings.duration}s forwards`;
    
    const transitionTimeout = setTimeout(() => {
        showMainContent();
    }, durationMs);

    document.getElementById("skip-intro").addEventListener("click", () => {
        clearTimeout(transitionTimeout);
        showMainContent();
    });
}

function showMainContent() {
    const introScreen = document.getElementById("intro-screen");
    const mainContent = document.getElementById("main-content");
    
    introScreen.classList.add("hidden");
    mainContent.classList.remove("hidden");
    
    const heroBtn = document.getElementById("hero-play-btn");
    const heroTitle = document.getElementById("hero-title");
    
    if (globalVideos.length > 0) {
        const featuredVideo = globalVideos[0];
        heroTitle.textContent = featuredVideo.name;
        heroBtn.onclick = () => playVideo(featuredVideo.id);
    } else {
        heroBtn.onclick = () => showToast("Nenhum v\u00EDdeo cadastrado no momento!");
    }
}

// 4. RENDERS DE CONTEÚDO (index.html)
function renderAllShelves() {
    const watchedList = JSON.parse(localStorage.getItem("sisgen_watched")) || [];

    const rowAlunos = document.getElementById("row-alunos");
    const rowInstrutores = document.getElementById("row-instrutores");
    const rowAdm = document.getElementById("row-adm");

    rowAlunos.innerHTML = "";
    rowInstrutores.innerHTML = "";
    rowAdm.innerHTML = "";

    const categories = {
        "Alunos": { container: rowAlunos, count: 0 },
        "Instrutores": { container: rowInstrutores, count: 0 },
        "Adm": { container: rowAdm, count: 0 }
    };

    globalVideos.forEach(video => {
        const isWatched = watchedList.includes(video.id);
        const cardClass = isWatched ? "watched" : "unwatched";
        const badgeText = isWatched ? "Visto" : "N&atilde;o Visto";
        
        const bgStyle = video.thumbnail 
            ? `style="background-image: url('${video.thumbnail}')"` 
            : `style="background-image: linear-gradient(135deg, var(--primary-blue) 0%, var(--bg-card) 100%)"`;

        const cardHtml = `
            <div class="video-card ${cardClass}" onclick="playVideo('${video.id}')">
                <div class="card-thumbnail" ${bgStyle}>
                    <div class="play-hover-btn"><i class="fas fa-play"></i></div>
                </div>
                <div class="card-content-overlay">
                    <h3 class="video-card-title">${video.name}</h3>
                    <div class="video-card-meta">
                        <span class="status-badge">${badgeText}</span>
                        <span class="video-duration"><i class="far fa-clock"></i> Aula</span>
                    </div>
                </div>
            </div>
        `;

        if (categories[video.category]) {
            // CORREÇÃO: Cria elementos DOM em vez de inserir HTML cru
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = cardHtml;
            while (tempDiv.firstChild) {
                categories[video.category].container.appendChild(tempDiv.firstChild);
            }
            categories[video.category].count++;
        }
    });

    Object.keys(categories).forEach(catName => {
        if (categories[catName].count === 0) {
            categories[catName].container.innerHTML = `<div class="empty-row-text">Nenhuma v&iacute;deo aula cadastrada para a categoria ${catName}.</div>`;
        }
    });
}

function applyCustomLogo() {
    const logoSettings = globalLogo;
    const navText = document.getElementById("nav-logo-text");
    const navImg = document.getElementById("nav-logo-img");

    if (logoSettings.type === "image" && logoSettings.imageUrl) {
        navText.classList.add("hidden");
        navImg.src = logoSettings.imageUrl;
        navImg.classList.remove("hidden");
    } else {
        navImg.classList.add("hidden");
        navText.innerHTML = logoSettings.text || "SisG<span>En</span> CURSOS";
        navText.classList.remove("hidden");
    }

    const heroBanner = document.getElementById("hero-banner");
    if (heroBanner) {
        const bgUrl = logoSettings.bannerBgUrl || 'https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=1600&auto=format&fit=crop';
        heroBanner.style.backgroundImage = `linear-gradient(to right, rgba(9, 12, 16, 0.9) 30%, rgba(9, 12, 16, 0.2) 70%), url('${bgUrl}')`;
    }
}

// 5. PLAYER DE VÍDEO
function playVideo(videoId) {
    const video = globalVideos.find(v => v.id === videoId);
    if (!video) return;

    markAsWatched(videoId);

    const modal = document.getElementById("player-modal");
    const container = document.getElementById("video-container");
    const modalTitle = document.getElementById("modal-video-title");
    const modalCategory = document.getElementById("modal-video-category");
    
    modalTitle.textContent = video.name;
    modalCategory.textContent = video.category;

    let videoUrl = video.url;
    // Converte http:// para https:// para evitar bloqueio de Mixed Content (recurso inseguro em site HTTPS)
    if (videoUrl.startsWith('http://')) {
        videoUrl = 'https://' + videoUrl.substring(7);
    }
    // Remove possíveis barras triplas acidentais (ex: http:/// ou https:///)
    videoUrl = videoUrl.replace(/^https:\/\/\/+/, 'https://');
    videoUrl = videoUrl.replace(/^http:\/\/\/+/, 'https://');

    let playerHtml = "";
    const parsedUrl = parseVideoUrl(videoUrl);

    if (parsedUrl.type === "youtube" || parsedUrl.type === "iframe") {
        playerHtml = `<iframe src="${parsedUrl.url}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>`;
    } else {
        // Encodar a URL do vídeo para que espaços e acentuações no arquivo funcionem no player
        let encodedUrl = parsedUrl.url;
        try {
            const urlObj = new URL(parsedUrl.url);
            urlObj.pathname = encodeURI(decodeURI(urlObj.pathname));
            encodedUrl = urlObj.toString();
        } catch (e) {
            encodedUrl = encodeURI(decodeURI(parsedUrl.url));
        }
        playerHtml = `
            <video src="${encodedUrl}" controls autoplay playsinline preload="auto">
                Seu navegador não suporta a tag de vídeo.
            </video>
        `;
    }

    container.innerHTML = playerHtml;
    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
}

function closePlayer() {
    const modal = document.getElementById("player-modal");
    const container = document.getElementById("video-container");
    
    container.innerHTML = "";
    modal.classList.add("hidden");
    document.body.style.overflow = "";
    
    renderAllShelves();
}

function parseVideoUrl(url) {
    if (url.includes('youtube.com/watch?v=')) {
        let videoId = url.split('v=')[1].split('&')[0];
        return { type: "youtube", url: `https://www.youtube.com/embed/${videoId}?autoplay=1&rel=0` };
    } else if (url.includes('youtu.be/')) {
        let videoId = url.split('youtu.be/')[1].split('?')[0];
        return { type: "youtube", url: `https://www.youtube.com/embed/${videoId}?autoplay=1&rel=0` };
    } else if (url.includes('youtube.com/embed/')) {
        return { type: "youtube", url: url };
    } else if (url.includes('1drv.ms')) {
        let embedUrl = url.replace(/\/v\//g, '/embed/').replace(/\/u\//g, '/embed/').replace(/\/w\//g, '/embed/');
        return { type: "iframe", url: embedUrl };
    } else if (url.includes('onedrive.live.com')) {
        let embedUrl = url;
        if (url.includes('redir?')) {
            embedUrl = url.replace('redir?', 'embed?');
        } else if (!url.includes('embed?')) {
            embedUrl = url + (url.includes('?') ? '&' : '?') + 'action=embedview';
        }
        return { type: "iframe", url: embedUrl };
    } else if (url.includes('sharepoint.com')) {
        let embedUrl = url;
        if (!url.includes('action=embedview')) {
            embedUrl = url + (url.includes('?') ? '&' : '?') + 'action=embedview';
        }
        return { type: "iframe", url: embedUrl };
    }
    return { type: "direct", url: url };
}

function markAsWatched(videoId) {
    let watchedList = JSON.parse(localStorage.getItem("sisgen_watched")) || [];
    if (!watchedList.includes(videoId)) {
        watchedList.push(videoId);
        localStorage.setItem("sisgen_watched", JSON.stringify(watchedList));
    }
}

function scrollRow(btn, direction) {
    const outerWrapper = btn.closest(".row-outer-wrapper");
    const carousel = outerWrapper.querySelector(".row-inner-carousel");
    const scrollAmount = 400;
    carousel.scrollBy({ left: scrollAmount * direction, behavior: "smooth" });
}

// 6. ADMIN PAGE LOGIC (admin.php)
// O admin.php chama initAdminPage após o DOMContentLoaded.
// Como o script carrega rápido, pode ser que globalVideos não tenha carregado se chamado do inline script,
// por isso agora aguardamos a carga da API aqui dentro.
async function initAdminPage() {
    if (globalVideos.length === 0 && !globalLogo.type) {
        await loadDataFromServer();
    }
    loadBrandingData();
    loadVideosTable();
    toggleLogoInputs();
    toggleBgInputs();
}

function loadBrandingData() {
    const logoSettings = globalLogo;
    const introSettings = globalIntro;

    document.getElementById("logo-type").value = logoSettings.type;
    document.getElementById("logo-text-input").value = logoSettings.text;
    
    const preview = document.getElementById("logo-preview");
    if (logoSettings.imageUrl) {
        preview.src = logoSettings.imageUrl;
        preview.classList.remove("hidden");
    }

    document.getElementById("bg-type").value = logoSettings.bannerBgType || "url";
    document.getElementById("bg-url-input").value = logoSettings.bannerBgUrl || "";
    
    const bgPreview = document.getElementById("bg-preview");
    if (logoSettings.bannerBgType === "upload" && logoSettings.bannerBgUrl) {
        bgPreview.src = logoSettings.bannerBgUrl;
        bgPreview.classList.remove("hidden");
    }

    document.getElementById("intro-logo-text").value = introSettings.logoText;
    document.getElementById("intro-subtext-input").value = introSettings.subtext;
    document.getElementById("intro-duration").value = introSettings.duration;
}

function toggleLogoInputs() {
    const type = document.getElementById("logo-type").value;
    const textGroup = document.getElementById("logo-text-group");
    const imgGroup = document.getElementById("logo-image-group");

    if (type === "image") {
        textGroup.classList.add("hidden");
        imgGroup.classList.remove("hidden");
    } else {
        imgGroup.classList.add("hidden");
        textGroup.classList.remove("hidden");
    }
}

let uploadedLogoBase64 = "";

function handleLogoUpload(input) {
    const file = input.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
        uploadedLogoBase64 = e.target.result;
        const preview = document.getElementById("logo-preview");
        preview.src = uploadedLogoBase64;
        preview.classList.remove("hidden");
    };
    reader.readAsDataURL(file);
}

function toggleBgInputs() {
    const type = document.getElementById("bg-type").value;
    const urlGroup = document.getElementById("bg-url-group");
    const uploadGroup = document.getElementById("bg-upload-group");

    if (type === "upload") {
        urlGroup.classList.add("hidden");
        uploadGroup.classList.remove("hidden");
    } else {
        uploadGroup.classList.add("hidden");
        urlGroup.classList.remove("hidden");
    }
}

let uploadedBgBase64 = "";

function handleBgUpload(input) {
    const file = input.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
        uploadedBgBase64 = e.target.result;
        const preview = document.getElementById("bg-preview");
        preview.src = uploadedBgBase64;
        preview.classList.remove("hidden");
    };
    reader.readAsDataURL(file);
}

async function saveLogoSettings() {
    const type = document.getElementById("logo-type").value;
    const textVal = document.getElementById("logo-text-input").value;
    const bgType = document.getElementById("bg-type").value;
    const bgUrlVal = document.getElementById("bg-url-input").value;
    
    globalLogo.type = type;
    globalLogo.text = textVal;
    globalLogo.bannerBgType = bgType;

    if (type === "image" && uploadedLogoBase64) {
        globalLogo.imageUrl = uploadedLogoBase64;
    }

    if (bgType === "upload" && uploadedBgBase64) {
        globalLogo.bannerBgUrl = uploadedBgBase64;
    } else if (bgType === "url") {
        globalLogo.bannerBgUrl = bgUrlVal;
    }

    const success = await saveToServer('save_logo', { logo: globalLogo });
    if (success) showToast("Identidade Visual salva com sucesso no Servidor!");
}

async function saveIntroSettings() {
    const introLogo = document.getElementById("intro-logo-text").value;
    const introSub = document.getElementById("intro-subtext-input").value;
    const introDur = parseFloat(document.getElementById("intro-duration").value) || 3;

    globalIntro = {
        logoText: introLogo,
        subtext: introSub,
        duration: introDur
    };

    const success = await saveToServer('save_intro', { intro: globalIntro });
    if (success) showToast("Configura\u00E7\u00F5es da intro salvas no Servidor!");
}

let draggedVideoIndex = null;

function loadVideosTable() {
    const tbody = document.getElementById("admin-video-list");
    tbody.innerHTML = "";

    if (globalVideos.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Nenhum v&iacute;deo cadastrado.</td></tr>`;
        return;
    }

    globalVideos.forEach((video, index) => {
        const tr = document.createElement("tr");
        tr.draggable = true;
        tr.dataset.index = index;
        
        tr.addEventListener("dragstart", function(e) {
            draggedVideoIndex = index;
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", index);
            setTimeout(() => tr.style.opacity = '0.5', 0);
        });

        tr.addEventListener("dragover", function(e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            const draggingRow = tbody.querySelector("tr[style*='opacity: 0.5']");
            if (!draggingRow) return;
            
            const currentOverIndex = index;
            if (draggedVideoIndex !== currentOverIndex) {
                const bounding = tr.getBoundingClientRect();
                const offset = bounding.y + (bounding.height / 2);
                if (e.clientY - offset > 0) {
                    tr.after(draggingRow);
                } else {
                    tr.before(draggingRow);
                }
            }
        });

        tr.addEventListener("dragend", async function(e) {
            tr.style.opacity = '1';
            
            // Recalcula o array baseado na nova ordem da DOM
            const rows = Array.from(tbody.querySelectorAll("tr"));
            const newVideosArray = [];
            rows.forEach(row => {
                const oldIndex = row.dataset.index;
                if(oldIndex !== undefined) {
                    newVideosArray.push(globalVideos[oldIndex]);
                }
            });
            
            // Verifica se a ordem realmente mudou
            let orderChanged = false;
            for(let i = 0; i < globalVideos.length; i++) {
                if(globalVideos[i].id !== newVideosArray[i].id) {
                    orderChanged = true;
                    break;
                }
            }

            if(orderChanged) {
                globalVideos = newVideosArray;
                const success = await saveToServer('save_videos', { videos: globalVideos });
                if (success) {
                    showToast("Ordem dos v\u00EDdeos atualizada no servidor!");
                    loadVideosTable(); // Atualiza índices (dataset.index) na UI
                }
            }
        });

        tr.innerHTML = `
            <td style="cursor: grab;">
                <i class="fas fa-grip-vertical" style="margin-right: 15px; color: var(--text-muted); cursor: grab;" title="Arraste para reordenar"></i>
                <strong>${video.name}</strong>
            </td>
            <td><span class="category-tag">${video.category}</span></td>
            <td style="max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                <a href="${video.url}" target="_blank" style="color: var(--primary-light);">${video.url}</a>
            </td>
            <td>
                <button onclick="deleteVideo('${video.id}')" class="btn-delete" title="Deletar V&iacute;deo">
                    <i class="fas fa-trash-can"></i>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function handleAddVideo(event) {
    event.preventDefault();
    
    const name = document.getElementById("video-name").value;
    const category = document.getElementById("video-category").value;
    const url = document.getElementById("video-url").value;
    const thumbnail = document.getElementById("video-thumbnail").value;

    const newVideo = {
        id: "v_" + Date.now(),
        name: name,
        category: category,
        url: url,
        thumbnail: thumbnail || null
    };

    globalVideos.push(newVideo);

    const success = await saveToServer('save_videos', { videos: globalVideos });
    if (success) {
        document.getElementById("add-video-form").reset();
        loadVideosTable();
        showToast("V\u00EDdeo adicionado com sucesso no Servidor!");
    }
}

async function deleteVideo(videoId) {
    if (confirm("Tem certeza que deseja excluir esta v\u00EDdeo aula para todos os alunos?")) {
        globalVideos = globalVideos.filter(v => v.id !== videoId);
        
        const success = await saveToServer('save_videos', { videos: globalVideos });
        
        if (success) {
            // Remove do local storage de visto do admin, se houver
            let watched = JSON.parse(localStorage.getItem("sisgen_watched")) || [];
            watched = watched.filter(id => id !== videoId);
            localStorage.setItem("sisgen_watched", JSON.stringify(watched));

            loadVideosTable();
            showToast("V\u00EDdeo removido.");
        }
    }
}

// Ações rápidas
function resetWatchedStatus() {
    localStorage.setItem("sisgen_watched", JSON.stringify([]));
    showToast("Hist\u00F3rico redefinido! Apenas para o seu navegador local.");
}

async function restoreDefaultVideos() {
    if (confirm("Deseja restaurar a lista inicial de v\u00EDdeos padr\u00E3o para todos os alunos? Isso limpar\u00E1 os v\u00EDdeos adicionados.")) {
        const success = await saveToServer('restore_defaults', {});
        if (success) {
            await loadDataFromServer();
            localStorage.setItem("sisgen_watched", JSON.stringify([]));
            loadVideosTable();
            showToast("Lista padr\u00E3o restaurada no Servidor.");
        }
    }
}

// 7. TOAST NOTIFICATIONS
function showToast(message) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.classList.remove("hidden");
    
    setTimeout(() => {
        toast.classList.add("hidden");
    }, 3000);
}
