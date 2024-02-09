const CHANCE_TRESHOLD = 0.3
const NEAR_BOTTOM_THRESHOLD = 1000
const PAGE_SIZE = 30;

const AnimationType = {
    SWIPE_LEFT: 'card-removal-swipe-left',
    SWIPE_RIGHT: 'card-removal-swipe-right',
    NONE: null // Representing no animation
};

function escapeHTML(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function formatDate(timestamp) {
    // Check if the timestamp is in seconds, and convert to milliseconds if needed
    // This check assumes that a timestamp in seconds would be a smaller number than '01-01-2000'
    if (timestamp < 946684800000) {
        timestamp *= 1000;
    }
    const options = { month: 'short', day: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
    const date = new Date(timestamp);
    const formattedDate = new Intl.DateTimeFormat('en-UK', options).format(date);
    return formattedDate;
}

function openEmail(message) {
    const url = '/api/open-email';  // adjust the domain and port as needed
    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(message)
    })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error(`Error: ${data.error}`);
            } else {
                console.log(data.status);
            }
        })
        .catch(error => {
            console.error('There was an error with the request:', error);
        });
}

// Throttle function to limit the number of calls to the scroll handler
function throttle(func, limit) {
    let inThrottle;
    return async function () {
        if (!inThrottle) {
            inThrottle = true;
            await func(() => inThrottle = false);
            setTimeout(() => (inThrottle = false), limit);
        }
    };
}

// Function to detect when the scroll is close to the bottom
function isNearBottom() {
    const position = window.scrollY + window.innerHeight;
    const height = document.documentElement.scrollHeight;
    return position > height - NEAR_BOTTOM_THRESHOLD;
}

async function onNearBottom(func) {
    async function callFuncIfNearBottom(resetThrottleFn) {
        if (isNearBottom()) {
            console.log('Near bottom, load next page');
            if (await func()) {
                resetThrottleFn();
                callFuncIfNearBottom(resetThrottleFn);
            }
        }
    }
    window.addEventListener('scroll', throttle(callFuncIfNearBottom, 50));
}


document.addEventListener("DOMContentLoaded", async () => {
    let isLoading = false;
    let lastEmailDate = null; // This will be updated with the date of the last email on the page
    let reachedEnd = false;
    let currentSectionIndex = 0; // New variable to track the current section index
    let sections = []; // New variable to hold the sections
    let tab = "general";

    const emailContainer = document.getElementById("emailContainer");
    const cardTemplateFuture = await fetch('/static/templates/cardTemplate.html');
    const cardTemplate = await cardTemplateFuture.text();
    const sectionTemplateFuture = await fetch('/static/templates/sectionTemplate.html');
    const sectionTemplate = await sectionTemplateFuture.text();

    async function appendSection(section) {
        function generateFiltersHtml(filters) {
            return filters.map(filter => `<li>${filter}</li>`).join('');
        }
        let emailSectionHtml = sectionTemplate
            .replace('{{display_name}}', section.display_name)
            .replace('{{filters}}', generateFiltersHtml(section.filters));
        emailContainer.insertAdjacentHTML('beforeend', emailSectionHtml.trim());
    }

    function removeConsecutiveSectionHeaders() {
        const sectionHeaders = document.querySelectorAll('.section-separator');
        sectionHeaders.forEach((header, index) => {
            let nextElement = header.nextElementSibling;
            if (nextElement && nextElement.matches('.section-separator')) {
                header.remove();
            }
        });
    }

    function removeOrphanSectionHeaders() {
        const sectionHeaders = document.querySelectorAll('.section-separator');
        sectionHeaders.forEach(header => {
            const nextElement = header.nextElementSibling;
            if (!nextElement) {
                header.remove();
            }
        });
    }

    async function appendCard(message) {
        const cardId = `${message.header_message_id}`;
        let emailCardHtml = cardTemplate.replace('{{id}}', cardId);
        emailContainer.insertAdjacentHTML('beforeend', emailCardHtml.trim());
        const card = document.getElementById(cardId);

        const hammertime = new Hammer(card);

        hammertime.on('swipeleft', function (e) {
            if (e.defaultPrevented) return
            console.log('Card was swiped left.');
            removeCard(message, 'SWIPE_LEFT');
        });

        hammertime.on('swiperight', function (e) {
            if (e.defaultPrevented) return
            console.log('Card was swiped right.');
            removeCard(message, 'SWIPE_RIGHT');
        });

        hammertime.on('tap', function () {
            openEmail(message);
        });

        updateCard(message);
    }

    async function removeCard(message, animationType = 'NONE') {
        function removeCardFromDom(card) {
            card.remove();
            removeConsecutiveSectionHeaders();
            removeOrphanSectionHeaders();
            loadIfNearBottom();
        }
        const cardId = `${message.header_message_id}`;
        const card = document.getElementById(cardId);
        if (!card) return;
        if (AnimationType[animationType]) {
            const animationClass = AnimationType[animationType];
            card.classList.add(animationClass);
            card.addEventListener('animationend', function () {
                removeCardFromDom(card);
            });
        } else {
            removeCardFromDom(card);
        }
    }

    async function updateCard(message) {
        const cardId = `${message.header_message_id}`;
        const card = document.getElementById(cardId);

        if (card) {
            // Update the elements within the card
            card.querySelector('.author-name').textContent = escapeHTML(message.author_name);
            card.querySelector('.author-email').textContent = escapeHTML(message.author_email);
            card.querySelector('.datetime').textContent = escapeHTML(formatDate(message.date));
            card.querySelector('.subject').textContent = escapeHTML(message.subject);

            // Hide or show elements as needed based on the new message data
            card.querySelector('.author-name').style.display = message.author_name ? 'block' : 'none';
            // card.querySelector('.our-account-name').style.display = account.identities[0].email == account.name ? 'none' : 'block';
            card.querySelector('.our-account-name').style.display = 'none'; // Or some other logic

            // Show or hide the loading indicator
            const loadingElement = card.querySelector('.loading-indicator');
            loadingElement.style.display = message.summary ? 'none' : 'block';

            // Update the summary text
            const summaryElement = card.querySelector('.card-text');
            summaryElement.textContent = message.summary?.summary;

            // Update the badges, if applicable
            const badges = card.querySelector('.badges');
            updateBadges(badges, message.summary);
        } else {
            console.error(`Card with ID ${cardId} not found.`);
        }
    }

    function updateBadges(badgesContainer, summary) {
        // Clear out any existing badges
        badgesContainer.innerHTML = '';

        // Add new badges based on the summary data
        if (summary) {
            for (let key in summary) {
                if (key.startsWith('is') && typeof summary[key] === 'number') {
                    const chance = summary[key];
                    if (chance > CHANCE_TRESHOLD) {
                        const style = key == "isWork" ? "badge-danger" : "badge-secondary";
                        const badge = document.createElement('span');
                        badge.className = `badge ${style} mr-2`;
                        badge.textContent = `${key.replace(/^is/, "")}: ${Math.round(chance * 100.0)}%`;
                        badgesContainer.appendChild(badge);
                    }
                }
            }
        }
    }

    async function appendCardIfNeeded(message) {
        const cardId = `${message.header_message_id}`;
        const card = document.getElementById(cardId);
        if (card) {
            await updateCard(message);
        } else {
            await appendCard(message);
        }
    }

    async function loadEmails(tab, section) {
        if (reachedEnd) {
            return false;
        }
        // Construct the URL with query parameters for pagination
        let query = `/api/tabs/${tab}/sections/${section.name}/emails?limit=${PAGE_SIZE}`;
        if (lastEmailDate) {
            query += `&start_from=${encodeURIComponent(lastEmailDate)}`;
        }

        const emailResponse = await fetch(query);
        const emails = await emailResponse.json();
        const emailContainer = document.getElementById("emailContainer");
        reachedEnd = emails.length < PAGE_SIZE;

        if (emails.length > 0) {
            // Update lastEmailDate with the date of the last email fetched
            lastEmailDate = emails[emails.length - 1].date;
        }

        console.log(`Loaded emails.`, emails);

        emails.forEach(async (message, idx) => {
            await appendCardIfNeeded(message);
        });
        return true;
    }

    async function loadSections(tab) {
        const sectionsResponse = await fetch(`/api/tabs/${tab}/sections`);
        sections = await sectionsResponse.json();
    }

    async function loadNext() {
        async function innerLoadNext() {
            if (sections === undefined || sections.length == 0) {
                await loadSections(tab);
                console.log(`Loaded sections.`, sections);
                appendSection(sections[currentSectionIndex]);
            }
            const section = sections[currentSectionIndex];
            if (section) {
                const moreEmailsAvailable = await loadEmails(tab, section);
                if (!moreEmailsAvailable) {
                    console.log(`Reached end of section ${section.name}.`);
                    currentSectionIndex++;
                    reachedEnd = false; // Reset reachedEnd for the next section
                    lastEmailDate = null; // Reset lastEmailDate for the next section
                    removeOrphanSectionHeaders();
                    appendSection(sections[currentSectionIndex]);
                    await innerLoadNext(); // Recursive call to load from the next section
                } else if (isNearBottom()) {
                    await innerLoadNext();
                }
            } else {
                console.log('Finished loading all sections.');
            }
        }
        if (isLoading) {
            return false;
        }
        isLoading = true;
        await innerLoadNext();
        isLoading = false;
        return true;
    }

    async function loadIfNearBottom() {
        if (isNearBottom()) {
            console.log('Near bottom, load next page');
            if (await loadNext()) {
                loadIfNearBottom();
            }
        }

    }

    loadNext();
    onNearBottom(loadNext);
});

const socket = io.connect('http://127.0.0.1:5000/');

socket.on('connect', function() {
    console.log('Connected to the server');
    socket.emit('frontend-hello', 'Hello from frontend page!');
});
