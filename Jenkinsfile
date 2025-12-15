pipeline {
    agent any
    options {
        timestamps()
    }
    environment {
        COMPOSE_FILE = 'docker-compose.yml'
        COMPOSE_PROJECT_NAME = 'unhinged_spyware'
    }
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        stage('Prepare Env File') {
            steps {
                withCredentials([file(credentialsId: 'tg-env-file', variable: 'TG_ENV_FILE')]) {
                    ansiColor('xterm') {
                        sh 'cp "$TG_ENV_FILE" .env'
                    }
                }
            }
        }
        stage('Detect Compose CLI') {
            steps {
                script {
                    env.COMPOSE_CMD = sh(
                        script: 'command -v "docker compose" >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose"',
                        returnStdout: true
                    ).trim()
                }
            }
        }
        stage('Build & Deploy') {
            steps {
                ansiColor('xterm') {
                    sh '''
                        set -e
                        COMPOSE_CMD=${COMPOSE_CMD:-"docker compose"}
                        $COMPOSE_CMD -f ${COMPOSE_FILE} pull || true
                        $COMPOSE_CMD -f ${COMPOSE_FILE} up -d --build --remove-orphans
                    '''
                }
            }
        }
    }
    post {
        always {
            ansiColor('xterm') {
                sh 'rm -f .env'
            }
        }
        failure {
            ansiColor('xterm') {
                sh '''
                    set +e
                    ${COMPOSE_CMD:-docker compose} -f ${COMPOSE_FILE:-docker-compose.yml} logs --tail 200
                '''
            }
        }
    }
}
