async function onInit() {
    let accounts = await messenger.accounts.list(true);
    let folders = accounts[0].folders;
    let folder = folders[0];
    let folderInfo = await messenger.folders.getFolderInfo(folder);
    let messages = await messenger.messages.list(folder);

    console.log(accounts);
    console.log(folderInfo);
    console.log(messages);

    let url = "http://127.0.0.1:5000/";
    let tabs = await browser.tabs.query();
    if (!tabs.find(tab => tab.url === url)) {
        browser.tabs.create({ "active" : true, "url" : url }).then((newTab) => {});
    }
}

function getPlainTextFromBody(parts) {
    for (let part of parts) {
        if (part.contentType === "text/plain") {
            return part.body;
        } else if (part.contentType === "text/html") {
            return part.body;
        } else if (part.parts) {
            // Recursive check in case there are nested parts
            const nestedResult = getPlainTextFromBody(part.parts);
            if (nestedResult) {
                return nestedResult;
            }
        }
    }
    return null;  // return null if neither text/plain nor text/html found
}


// RUN

onInit();

// REST

async function postMessages(messages) {
    const endpoint = 'http://127.0.0.1:5000/api/emails';
    const requestOptions = {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(messages, null, 2)
    };
    try {
        const response = await fetch(endpoint, requestOptions);
        let responseData;
        try {
            responseData = await response.json();
        } catch (parseError) {
            console.error(`Failed to parse response as JSON (HTTP Status: ${response.status}):`, parseError);
            throw parseError;
        }
        if (response.ok) {
            console.log(`Successfully added messages (HTTP Status: ${response.status}):`, responseData);
            return responseData;
        } else {
            console.error(`Error adding messages (HTTP Status: ${response.status}):`, responseData);
            throw new Error(responseData.message || "Unknown error");
        }
    } catch (error) {
        console.error("Failed to post messages:", error);
    }
}

// SOCKET

const socket = io.connect('http://127.0.0.1:5000/');

socket.on('connect', function() {
    console.log('Connected to the server');
    socket.emit('thunderbridge-hello', 'Hello from Thunderbird plugin!');
});

socket.on('fetch-emails', async function(data) {
    console.log(`fetch-emails: ${data}`);
    let accounts = await messenger.accounts.list(true);
    let folders = accounts[0].folders;
    let folder = folders[0];
    let folderInfo = await messenger.folders.getFolderInfo(folder);
    let startAt = 0;

    let page = await messenger.messages.list(folder);
    page.startAt = startAt;
    page.total = folderInfo.totalMessageCount;
    console.log(`sending page:`, page);
    startAt += page.messages.length;
    await postMessages(page);

    while (page.id) {
        page = await messenger.messages.continueList(page.id);
        page.startAt = startAt;
        page.total = folderInfo.totalMessageCount;
        console.log(`sending page:`, page);
        startAt += page.messages.length;
        await postMessages(page);
    }
});

socket.on('request_email_body', async (data, callback) => {
    console.log(`request_email_body:`, data);
    let messages = await messenger.messages.query({"headerMessageId" : data['header_message_id']});
    let message = messages.messages[0];
    var messageFull = await messenger.messages.getFull(message.id);
    const messageBody = getPlainTextFromBody(messageFull.parts);
    console.log(`body:`, messageBody);
    callback(messageBody);
});

socket.on('open-email', async function(data) {
    console.log(`open-email:`, data);
    let messages = await messenger.messages.query({"headerMessageId" : data['header_message_id']});
    let message = messages.messages[0];
    messenger.messageDisplay.open({ active: true, headerMessageId: message.headerMessageId, messageId: message.messageId });
    let window = await messenger.windows.getCurrent();
    messenger.windows.update(window.id, { "focused" : true });
});
