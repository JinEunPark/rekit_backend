pipeline {
    agent any

    environment {
        REGISTRY         = '127.0.0.1:5000'
        IMAGE_NAME       = 'rekit-backend'
        COMPOSE_PROJECT  = 'rekit-backend'
        // 저장소에는 커밋하지 않는 운영용 .env — 호스트의 고정 경로에서 배포 시점에 복사해온다
        PROD_ENV_FILE    = '/home/wlsdms/rekit/secrets/rekit_backend.env'
    }

    stages {
        stage('Build & Push') {
            steps {
                script {
                    env.IMAGE_TAG = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
                }
                sh """
                    docker build \
                      -t ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} \
                      -t ${REGISTRY}/${IMAGE_NAME}:latest \
                      .
                    docker push ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
                    docker push ${REGISTRY}/${IMAGE_NAME}:latest
                """
            }
        }

        stage('Deploy') {
            steps {
                sh """
                    cp ${PROD_ENV_FILE} .env
                    docker compose -p ${COMPOSE_PROJECT} -f docker-compose.prod.yml pull app
                    docker compose -p ${COMPOSE_PROJECT} -f docker-compose.prod.yml up -d postgres redis app
                    docker image prune -f
                """
            }
        }
    }

    post {
        always {
            sh 'rm -f .env'
        }
    }
}
