from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .intents import process_message


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat(request):
    message = (request.data.get('message') or '').strip()
    if not message:
        return Response({'error': 'message is required'}, status=status.HTTP_400_BAD_REQUEST)

    team = request.user.active_team
    if not team:
        return Response({
            'reply': (
                "You don't have an active team yet. "
                "Please create or join a team to get started."
            ),
            'type': 'no_team',
            'data': None,
        })

    result = process_message(team, message)
    return Response(result)
